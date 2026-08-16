"""OHDSI Athena vocabulary loader → ``omop_concept`` (BIGINT-safe).

Streams Athena ``CONCEPT.csv`` / ``CONCEPT.tsv`` in pandas chunks, filters to
RxNorm / RxNorm Extension / MedDRA / SNOMED*, and bulk-upserts with
``ON CONFLICT (concept_id) DO NOTHING``.

Usage::

    python -m app.etl_pipeline.load_athena_vocab --concept-csv /data/CONCEPT.csv
    python -m app.etl_pipeline.load_athena_vocab   # offline surrogate seed fallback
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

LOGGER = logging.getLogger("vigilai.etl.load_athena_vocab")

TARGET_VOCABS = frozenset({
    "RxNorm",
    "RxNorm Extension",
    "MedDRA",
    "SNOMED",
    "SNOMED CT",
    "SNOMED-CT",
})

CONCEPT_COLUMNS = (
    "concept_id",
    "concept_name",
    "domain_id",
    "vocabulary_id",
    "concept_class_id",
    "standard_concept",
    "concept_code",
    "valid_start_date",
    "valid_end_date",
    "invalid_reason",
)

UPSERT_SQL = """
INSERT INTO omop_concept (
    concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
    standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason
) VALUES (
    :concept_id, :concept_name, :domain_id, :vocabulary_id, :concept_class_id,
    :standard_concept, :concept_code, :valid_start_date, :valid_end_date, :invalid_reason
)
ON CONFLICT (concept_id) DO NOTHING
"""

DEFAULT_CHUNK = 10_000


def _configure_logging(verbose: bool = False) -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOGGER.propagate = False


def _sync_engine(database_url: Optional[str] = None) -> Engine:
    load_dotenv()
    raw = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise EnvironmentError(
            "DATABASE_URL is not set. Example: postgresql://user:pass@localhost:5432/vigilai"
        )
    url = make_url(raw)
    driver = (url.drivername or "").lower()
    if "asyncpg" in driver:
        url = url.set(drivername="postgresql+psycopg2")
    elif driver in {"postgresql", "postgres"}:
        # prefer psycopg2 for sync COPY-friendly path; fall back to bare postgresql
        try:
            import psycopg2  # noqa: F401
            url = url.set(drivername="postgresql+psycopg2")
        except ImportError:
            url = url.set(drivername="postgresql")
    if driver.startswith("sqlite"):
        LOGGER.warning("SQLite detected — Athena bulk load is supported but COPY is skipped")
    return create_engine(url.render_as_string(hide_password=False), pool_pre_ping=True)


def _parse_athena_date(value: Any) -> date:
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return date(1970, 1, 1)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "null"}:
        return date(1970, 1, 1)
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10] if "-" in s or "/" in s else s[:8], fmt).date()
        except ValueError:
            continue
    return date(1970, 1, 1)


def _safe_str(value: Any, *, maxlen: int, default: str = "") -> str:
    if value is None or (isinstance(value, float) and value != value):
        return default
    text_v = str(value).strip()
    if not text_v or text_v.lower() in {"nan", "none", "null"}:
        return default
    return text_v[:maxlen]


def _safe_optional_str(value: Any, *, maxlen: int) -> Optional[str]:
    s = _safe_str(value, maxlen=maxlen, default="")
    return s or None


def _safe_bigint(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and value != value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None


def _normalize_vocab(value: Any) -> str:
    return _safe_str(value, maxlen=20)


def iter_athena_concept_chunks(
    concept_path: Path,
    *,
    chunksize: int = DEFAULT_CHUNK,
    vocabularies: Optional[Sequence[str]] = None,
) -> Iterator[List[dict[str, Any]]]:
    """Yield filtered concept row dicts from an Athena CONCEPT dump."""
    import pandas as pd

    allowed = frozenset(vocabularies) if vocabularies else TARGET_VOCABS
    sep = "\t" if concept_path.suffix.lower() in {".tsv", ".txt"} else ","
    # Athena CONCEPT.csv is often tab-separated even with .csv suffix — sniff
    with concept_path.open("r", encoding="utf-8", errors="replace") as fh:
        head = fh.readline()
    if "\t" in head and sep == ",":
        sep = "\t"

    reader = pd.read_csv(
        concept_path,
        sep=sep,
        dtype=str,
        chunksize=chunksize,
        keep_default_na=False,
        na_filter=False,
        low_memory=False,
        encoding="utf-8",
        on_bad_lines="skip",
    )

    for chunk in reader:
        # Normalize column names (Athena sometimes uses uppercase)
        chunk.columns = [str(c).strip().lower() for c in chunk.columns]
        required = {"concept_id", "concept_name", "vocabulary_id", "concept_code"}
        missing = required - set(chunk.columns)
        if missing:
            raise ValueError(f"{concept_path} missing columns: {sorted(missing)}")

        rows: List[dict[str, Any]] = []
        for rec in chunk.to_dict(orient="records"):
            vocab = _normalize_vocab(rec.get("vocabulary_id"))
            if vocab not in allowed:
                # Case-insensitive match for SNOMED variants
                if not any(vocab.lower() == a.lower() for a in allowed):
                    continue
            cid = _safe_bigint(rec.get("concept_id"))
            if cid is None or cid <= 0:
                continue
            code = _safe_str(rec.get("concept_code"), maxlen=50)
            name = _safe_str(rec.get("concept_name"), maxlen=255, default=code or str(cid))
            if not code:
                continue
            rows.append({
                "concept_id": cid,
                "concept_name": name,
                "domain_id": _safe_str(rec.get("domain_id"), maxlen=20, default="Undefined"),
                "vocabulary_id": vocab[:20],
                "concept_class_id": _safe_str(
                    rec.get("concept_class_id"), maxlen=20, default="Undefined"
                ),
                "standard_concept": _safe_optional_str(rec.get("standard_concept"), maxlen=1),
                "concept_code": code,
                "valid_start_date": _parse_athena_date(rec.get("valid_start_date")),
                "valid_end_date": _parse_athena_date(rec.get("valid_end_date")) or date(2099, 12, 31),
                "invalid_reason": _safe_optional_str(rec.get("invalid_reason"), maxlen=1),
            })
        if rows:
            yield rows


def _ensure_omop_concept_table(engine: Engine) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS omop_concept (
        concept_id BIGINT PRIMARY KEY,
        concept_name VARCHAR(255) NOT NULL,
        domain_id VARCHAR(20) NOT NULL,
        vocabulary_id VARCHAR(20) NOT NULL,
        concept_class_id VARCHAR(20) NOT NULL,
        standard_concept VARCHAR(1) NULL,
        concept_code VARCHAR(50) NOT NULL,
        valid_start_date DATE NOT NULL,
        valid_end_date DATE NOT NULL,
        invalid_reason VARCHAR(1) NULL
    )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
        # Widen legacy INTEGER PK if needed (Postgres)
        if conn.dialect.name == "postgresql":
            conn.execute(text(
                "ALTER TABLE omop_concept ALTER COLUMN concept_id TYPE BIGINT"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_omop_concept_vocab_code "
                "ON omop_concept (vocabulary_id, concept_code)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_omop_concept_name "
                "ON omop_concept (concept_name)"
            ))


def _bulk_upsert_chunk(engine: Engine, rows: Sequence[dict[str, Any]]) -> int:
    if not rows:
        return 0
    if engine.dialect.name == "postgresql":
        return _copy_upsert_postgres(engine, rows)
    # SQLite / other — executemany style upsert
    inserted = 0
    with engine.begin() as conn:
        for row in rows:
            result = conn.execute(text(UPSERT_SQL), row)
            inserted += result.rowcount or 0
    return inserted


def _copy_upsert_postgres(engine: Engine, rows: Sequence[dict[str, Any]]) -> int:
    """Temp-table + COPY + INSERT…ON CONFLICT for high-throughput Athena loads."""
    import io

    buf = io.StringIO()
    for r in rows:
        std = r["standard_concept"] if r["standard_concept"] is not None else ""
        inv = r["invalid_reason"] if r["invalid_reason"] is not None else ""
        # COPY text format — tab separated, escape newlines
        fields = [
            str(r["concept_id"]),
            r["concept_name"].replace("\\", "\\\\").replace("\t", " ").replace("\n", " "),
            r["domain_id"],
            r["vocabulary_id"],
            r["concept_class_id"],
            std,
            r["concept_code"].replace("\\", "\\\\").replace("\t", " "),
            r["valid_start_date"].isoformat(),
            r["valid_end_date"].isoformat(),
            inv,
        ]
        buf.write("\t".join(fields) + "\n")
    buf.seek(0)

    raw_url = engine.url.render_as_string(hide_password=False)
    # Use psycopg2 COPY when available
    try:
        import psycopg2
    except ImportError:
        inserted = 0
        with engine.begin() as conn:
            for row in rows:
                result = conn.execute(text(UPSERT_SQL), row)
                inserted += max(result.rowcount or 0, 0)
        return inserted

    # Convert SQLAlchemy URL to libpq DSN
    u = make_url(raw_url)
    dsn = (
        f"host={u.host or 'localhost'} port={u.port or 5432} dbname={u.database} "
        f"user={u.username or ''} password={u.password or ''}"
    )
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE tmp_athena_concept (
                    LIKE omop_concept INCLUDING DEFAULTS
                ) ON COMMIT DROP
                """
            )
            cur.copy_from(
                buf,
                "tmp_athena_concept",
                sep="\t",
                columns=list(CONCEPT_COLUMNS),
                null="",
            )
            cur.execute(
                """
                INSERT INTO omop_concept (
                    concept_id, concept_name, domain_id, vocabulary_id, concept_class_id,
                    standard_concept, concept_code, valid_start_date, valid_end_date, invalid_reason
                )
                SELECT
                    concept_id,
                    concept_name,
                    domain_id,
                    vocabulary_id,
                    concept_class_id,
                    NULLIF(standard_concept, ''),
                    concept_code,
                    valid_start_date,
                    valid_end_date,
                    NULLIF(invalid_reason, '')
                FROM tmp_athena_concept
                ON CONFLICT (concept_id) DO NOTHING
                """
            )
            inserted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_athena_vocab(
    *,
    concept_csv: Optional[Path] = None,
    database_url: Optional[str] = None,
    chunksize: int = DEFAULT_CHUNK,
    vocabularies: Optional[Sequence[str]] = None,
    fallback_surrogates: bool = True,
) -> dict[str, Any]:
    """Load Athena CONCEPT dump into ``omop_concept`` (or surrogate seed)."""
    engine = _sync_engine(database_url)
    _ensure_omop_concept_table(engine)

    if concept_csv is None or not Path(concept_csv).is_file():
        if not fallback_surrogates:
            raise FileNotFoundError(
                f"CONCEPT file not found: {concept_csv!s}. Pass --concept-csv or enable fallback."
            )
        LOGGER.warning(
            "No Athena CONCEPT file at %s — seeding offline RxE/MCN surrogates",
            concept_csv,
        )
        from ..database import SessionLocal, init_db
        from ..db.omop_concept_seed import seed_concepts_from_surrogates

        init_db()
        db = SessionLocal()
        try:
            result = seed_concepts_from_surrogates(db)
            db.commit()
            return {
                "mode": "surrogate_fallback",
                "path": None,
                "chunks": 0,
                "rows_upserted": int(result.get("concepts_upserted") or result.get("n_drug", 0))
                + int(result.get("n_cond", 0) or 0),
                **result,
            }
        finally:
            db.close()

    path = Path(concept_csv)
    LOGGER.info("Loading Athena concepts from %s (chunksize=%d)", path, chunksize)
    total_read = 0
    total_upserted = 0
    chunks = 0
    for batch in iter_athena_concept_chunks(
        path, chunksize=chunksize, vocabularies=vocabularies
    ):
        chunks += 1
        total_read += len(batch)
        n = _bulk_upsert_chunk(engine, batch)
        total_upserted += n
        LOGGER.info(
            "Chunk %d — read=%d upserted≈%d (cumulative read=%d)",
            chunks,
            len(batch),
            n,
            total_read,
        )

    with engine.connect() as conn:
        count = int(conn.execute(text("SELECT COUNT(*) FROM omop_concept")).scalar_one())

    return {
        "mode": "athena_csv",
        "path": str(path),
        "chunks": chunks,
        "rows_read_filtered": total_read,
        "rows_upserted": total_upserted,
        "omop_concept_total": count,
        "vocabularies": sorted(vocabularies or TARGET_VOCABS),
    }


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Load OHDSI Athena CONCEPT into omop_concept")
    parser.add_argument(
        "--concept-csv",
        type=Path,
        default=None,
        help="Path to Athena CONCEPT.csv / CONCEPT.tsv",
    )
    parser.add_argument("--chunksize", type=int, default=DEFAULT_CHUNK)
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="Fail if CONCEPT file is missing (do not seed surrogates)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)
    try:
        result = load_athena_vocab(
            concept_csv=args.concept_csv,
            database_url=args.database_url,
            chunksize=args.chunksize,
            fallback_surrogates=not args.no_fallback,
        )
        LOGGER.info("Athena vocab load complete: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("load_athena_vocab failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
