"""Streaming openFDA / FAERS JSON → OMOP person / drug_exposure / condition_occurrence.

Processes quarterly FAERS JSON dumps or live openFDA ``/drug/event`` payloads in
batches of 5,000 events. Maps drug names and MedDRA PTs to ``omop_concept``
BIGINT identifiers. Idempotent via ``person_source_value`` unique key and
deterministic exposure/condition natural keys.

Usage::

    python -m app.etl_pipeline.ingest_faers --faers-json /data/faers_q.json
    python -m app.etl_pipeline.ingest_faers --limit 5000
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

LOGGER = logging.getLogger("vigilai.etl.ingest_faers")

DEFAULT_BATCH = 5_000
GENDER_MALE = 8507
GENDER_FEMALE = 8532
GENDER_UNKNOWN = 0
DRUG_TYPE_PRESCRIBED = 38000177
CONDITION_TYPE_AE = 32879

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "ingestion"
    / "fixtures"
    / "faers_bulk_sample.json"
)


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


def _to_async_url(raw: str) -> str:
    url = make_url(raw.strip())
    driver = (url.drivername or "").lower()
    if "asyncpg" in driver:
        return url.render_as_string(hide_password=False)
    if driver in {"postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"}:
        return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    if driver.startswith("sqlite"):
        raise ValueError("ingest_faers requires PostgreSQL (asyncpg)")
    raise ValueError(f"Unsupported DATABASE_URL dialect: {driver!r}")


def _stable_bigint(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _parse_date(raw: Any) -> Optional[date]:
    if raw is None or raw == "":
        return None
    s = str(raw).strip()
    for fmt, n in (("%Y%m%d", 8), ("%Y-%m-%d", 10), ("%Y-%m-%dT%H:%M:%S", 19)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    return None


def _map_gender(patient: dict) -> Tuple[int, Optional[str]]:
    sex = (patient.get("patientsex") or patient.get("sex") or "").strip()
    # openFDA: 0=unknown, 1=male, 2=female
    if sex in {"1", "M", "m", "Male", "male", "MALE"}:
        return GENDER_MALE, "M"
    if sex in {"2", "F", "f", "Female", "female", "FEMALE"}:
        return GENDER_FEMALE, "F"
    return GENDER_UNKNOWN, sex or None


def _year_of_birth(patient: dict) -> Optional[int]:
    age_raw = patient.get("patientonsetage")
    unit = str(patient.get("patientonsetageunit") or "").strip()
    try:
        age = float(age_raw)
    except (TypeError, ValueError):
        return None
    # 800=Decade, 801=Year, 802=Month, 803=Week, 804=Day, 805=Hour
    if unit in {"801", "Year", "Years", "YR", "yr", ""}:
        years = age
    elif unit in {"800"}:
        years = age * 10
    elif unit in {"802", "Month", "Months", "MON"}:
        years = age / 12.0
    elif unit in {"803", "Week", "Weeks", "WK"}:
        years = age / 52.0
    elif unit in {"804", "Day", "Days", "DY"}:
        years = age / 365.25
    else:
        years = age
    if years < 0 or years > 120:
        return None
    return max(1900, datetime.utcnow().year - int(years))


def _drug_names(drug: dict) -> List[str]:
    names: List[str] = []
    mp = (drug.get("medicinalproduct") or "").strip()
    if mp:
        names.append(mp)
    openfda = drug.get("openfda") or {}
    for key in ("generic_name", "brand_name", "substance_name"):
        vals = openfda.get(key) or []
        if isinstance(vals, str):
            vals = [vals]
        for v in vals:
            v = str(v).strip()
            if v and v.lower() not in {n.lower() for n in names}:
                names.append(v)
    return names


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


class ConceptResolver:
    """In-memory name/code → concept_id lookup built from ``omop_concept``."""

    def __init__(self) -> None:
        self.by_vocab_name: Dict[Tuple[str, str], int] = {}
        self.by_vocab_code: Dict[Tuple[str, str], int] = {}
        self.by_name: Dict[str, int] = {}

    async def load(self, conn: AsyncConnection) -> int:
        result = await conn.execute(
            text(
                """
                SELECT concept_id, concept_name, vocabulary_id, concept_code
                FROM omop_concept
                WHERE vocabulary_id IN (
                    'RxNorm', 'RxNorm Extension', 'MedDRA', 'SNOMED',
                    'SNOMED CT', 'SNOMED-CT', 'FAERS', 'SIDER'
                )
                """
            )
        )
        n = 0
        for row in result.mappings():
            cid = int(row["concept_id"])
            vocab = str(row["vocabulary_id"] or "")
            name = _normalize_name(str(row["concept_name"] or ""))
            code = str(row["concept_code"] or "").strip().lower()
            if name:
                self.by_vocab_name[(vocab.lower(), name)] = cid
                self.by_name.setdefault(name, cid)
            if code:
                self.by_vocab_code[(vocab.lower(), code)] = cid
            n += 1
        LOGGER.info("Loaded %d concepts into resolver cache", n)
        return n

    def resolve_drug(self, name: str) -> Optional[int]:
        key = _normalize_name(name)
        for vocab in ("rxnorm", "rxnorm extension", "sider", "faers", "snomed"):
            cid = self.by_vocab_name.get((vocab, key))
            if cid is not None:
                return cid
        return self.by_name.get(key)

    def resolve_condition(self, pt: str) -> Optional[int]:
        key = _normalize_name(pt)
        for vocab in ("meddra", "snomed", "snomed ct", "snomed-ct"):
            cid = self.by_vocab_name.get((vocab, key))
            if cid is not None:
                return cid
        return self.by_name.get(key)


async def _ensure_schema(conn: AsyncConnection) -> None:
    """Idempotency indexes + BIGINT wideners for cumulative FAERS loads."""
    statements = [
        "ALTER TABLE IF EXISTS omop_person ALTER COLUMN person_id TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_person ALTER COLUMN gender_concept_id TYPE BIGINT",
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_omop_person_source_value
        ON omop_person (person_source_value)
        WHERE person_source_value IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_omop_drug_exposure_natural
        ON omop_drug_exposure (person_id, drug_source_value, drug_exposure_start_date)
        WHERE drug_source_value IS NOT NULL AND drug_exposure_start_date IS NOT NULL
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_omop_condition_natural
        ON omop_condition_occurrence (person_id, condition_source_value, condition_start_date)
        WHERE condition_source_value IS NOT NULL AND condition_start_date IS NOT NULL
        """,
    ]
    for sql in statements:
        try:
            await conn.execute(text(sql))
        except Exception as exc:  # noqa: BLE001 — SQLite / missing table soft-fail
            LOGGER.debug("Schema ensure skip: %s (%s)", sql[:60], exc)


def _iter_json_file_events(path: Path) -> Iterator[dict]:
    """Stream events from a FAERS/openFDA JSON file without loading entire dump."""
    # Prefer ijson for huge arrays; fall back to json.load for fixtures
    try:
        import ijson  # type: ignore
    except ImportError:
        ijson = None  # type: ignore

    if ijson is not None:
        with path.open("rb") as fh:
            # Try results[].event or top-level array
            try:
                for event in ijson.items(fh, "results.item"):
                    if isinstance(event, dict):
                        yield event
                return
            except Exception:
                fh.seek(0)
            try:
                for event in ijson.items(fh, "item"):
                    if isinstance(event, dict):
                        yield event
                return
            except Exception:
                fh.seek(0)

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        results = raw.get("results") or raw.get("events") or []
    elif isinstance(raw, list):
        results = raw
    else:
        results = []
    for event in results:
        if isinstance(event, dict):
            # Fixture rows may be simplified — normalize
            if "patient" not in event and ("drugs" in event or "drug" in event):
                drugs = event.get("drugs") or [event.get("drug")]
                reactions = event.get("reactions") or [event.get("reaction")]
                yield {
                    "safetyreportid": str(
                        event.get("external_id") or event.get("safetyreportid") or ""
                    ).replace("faers_bulk:", ""),
                    "receiptdate": str(event.get("posted_at") or "").replace("-", "")[:8],
                    "patient": {
                        "drug": [{"medicinalproduct": d} for d in drugs if d],
                        "reaction": [{"reactionmeddrapt": r} for r in reactions if r],
                    },
                }
            else:
                yield event


def _iter_openfda_api(limit: int) -> Iterator[dict]:
    try:
        import httpx
    except ImportError:
        LOGGER.warning("httpx not installed — skipping live openFDA pull")
        return
        yield  # pragma: no cover

    fetched = 0
    skip = 0
    page = 100
    try:
        with httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "VigilAI-ETL/2.0 (FAERS ingest)"},
        ) as client:
            while fetched < limit:
                n = min(page, limit - fetched)
                resp = client.get(
                    "https://api.fda.gov/drug/event.json",
                    params={"search": "serious:1", "limit": n, "skip": skip},
                )
                if resp.status_code != 200:
                    LOGGER.warning("openFDA HTTP %s — stopping", resp.status_code)
                    break
                results = resp.json().get("results") or []
                if not results:
                    break
                for event in results:
                    yield event
                fetched += len(results)
                skip += len(results)
                if len(results) < n:
                    break
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("openFDA unavailable: %s", exc)


def _batched(iterable: Iterable[dict], size: int) -> Iterator[List[dict]]:
    batch: List[dict] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _transform_event(
    event: dict,
    resolver: ConceptResolver,
    *,
    project_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Map one FAERS/openFDA event into OMOP row payloads."""
    try:
        safety = str(event.get("safetyreportid") or "").strip()
        if not safety:
            safety = hashlib.sha1(repr(event).encode("utf-8")).hexdigest()[:16]
        patient = event.get("patient") or {}
        if not isinstance(patient, dict):
            return None

        gender_cid, gender_src = _map_gender(patient)
        yob = _year_of_birth(patient)
        recv = _parse_date(event.get("receiptdate") or event.get("receivedate")) or date.today()
        person_source = f"faers:{safety}"[:50]
        person_id = _stable_bigint("faers_person", safety)

        drugs_out: List[dict[str, Any]] = []
        for drug in patient.get("drug") or []:
            if not isinstance(drug, dict):
                continue
            for name in _drug_names(drug):
                cid = resolver.resolve_drug(name)
                char = str(drug.get("drugcharacterization") or "1")
                drugs_out.append({
                    "person_id": person_id,
                    "drug_concept_id": (name.upper()[:64] if cid is None else str(cid)),
                    "drug_concept_id_int": cid,
                    "drug_source_value": name[:256],
                    "drug_exposure_start_date": recv,
                    "drug_type_concept_id": DRUG_TYPE_PRESCRIBED if char == "1" else 38000180,
                    "project_id": project_id,
                })

        conditions_out: List[dict[str, Any]] = []
        for reaction in patient.get("reaction") or []:
            if not isinstance(reaction, dict):
                continue
            pt = (reaction.get("reactionmeddrapt") or reaction.get("reactionmeddrapt") or "").strip()
            if not pt:
                continue
            cid = resolver.resolve_condition(pt)
            conditions_out.append({
                "person_id": person_id,
                "condition_concept_id": (pt.upper()[:128] if cid is None else str(cid)),
                "condition_concept_id_int": cid,
                "condition_source_value": pt[:256],
                "condition_start_date": recv,
                "condition_type_concept_id": CONDITION_TYPE_AE,
                "is_expected_baseline": False,
                "project_id": project_id,
            })

        if not drugs_out and not conditions_out:
            return None

        return {
            "person": {
                "person_id": person_id,
                "gender_concept_id": gender_cid,
                "year_of_birth": yob,
                "race_concept_id": 0,
                "ethnicity_concept_id": 0,
                "person_source_value": person_source,
                "gender_source_value": gender_src,
                "author_hash": hashlib.sha256(person_source.encode()).hexdigest()[:32],
                "project_id": project_id,
            },
            "drugs": drugs_out,
            "conditions": conditions_out,
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Malformed FAERS event skipped: %s", exc)
        return None


async def _flush_batch(
    conn: AsyncConnection,
    transformed: Sequence[dict[str, Any]],
) -> dict[str, int]:
    persons = drugs = conditions = 0
    for row in transformed:
        p = row["person"]
        result = await conn.execute(
            text(
                """
                INSERT INTO omop_person (
                    person_id, gender_concept_id, year_of_birth,
                    race_concept_id, ethnicity_concept_id,
                    person_source_value, gender_source_value,
                    author_hash, project_id, created_at
                ) VALUES (
                    :person_id, :gender_concept_id, :year_of_birth,
                    :race_concept_id, :ethnicity_concept_id,
                    :person_source_value, :gender_source_value,
                    :author_hash, :project_id, NOW()
                )
                ON CONFLICT (person_id) DO NOTHING
                """
            ),
            p,
        )
        if (result.rowcount or 0) > 0:
            persons += 1
            person_id = int(p["person_id"])
        else:
            # Cumulative re-run: reuse existing person (by PK or FAERS source key)
            existing = await conn.execute(
                text(
                    """
                    SELECT person_id FROM omop_person
                    WHERE person_id = :pid
                       OR person_source_value = :psv
                    ORDER BY CASE WHEN person_id = :pid THEN 0 ELSE 1 END
                    LIMIT 1
                    """
                ),
                {"pid": p["person_id"], "psv": p["person_source_value"]},
            )
            found = existing.scalar_one_or_none()
            person_id = int(found) if found is not None else int(p["person_id"])

        for d in row["drugs"]:
            payload = {**d, "person_id": person_id}
            try:
                r = await conn.execute(
                    text(
                        """
                        INSERT INTO omop_drug_exposure (
                            person_id, drug_concept_id, drug_concept_id_int,
                            drug_source_value, drug_exposure_start_date,
                            drug_type_concept_id, project_id, created_at
                        ) VALUES (
                            :person_id, :drug_concept_id, :drug_concept_id_int,
                            :drug_source_value, :drug_exposure_start_date,
                            :drug_type_concept_id, :project_id, NOW()
                        )
                        ON CONFLICT (person_id, drug_source_value, drug_exposure_start_date)
                        WHERE drug_source_value IS NOT NULL AND drug_exposure_start_date IS NOT NULL
                        DO NOTHING
                        """
                    ),
                    payload,
                )
                if (r.rowcount or 0) > 0:
                    drugs += 1
            except Exception:
                # SQLite / missing partial unique — plain insert ignore duplicates via select
                exists = await conn.execute(
                    text(
                        """
                        SELECT 1 FROM omop_drug_exposure
                        WHERE person_id = :person_id
                          AND drug_source_value = :drug_source_value
                          AND drug_exposure_start_date = :drug_exposure_start_date
                        LIMIT 1
                        """
                    ),
                    payload,
                )
                if exists.first() is None:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO omop_drug_exposure (
                                person_id, drug_concept_id, drug_concept_id_int,
                                drug_source_value, drug_exposure_start_date,
                                drug_type_concept_id, project_id, created_at
                            ) VALUES (
                                :person_id, :drug_concept_id, :drug_concept_id_int,
                                :drug_source_value, :drug_exposure_start_date,
                                :drug_type_concept_id, :project_id, NOW()
                            )
                            """
                        ),
                        payload,
                    )
                    drugs += 1

        for c in row["conditions"]:
            payload = {**c, "person_id": person_id}
            try:
                r = await conn.execute(
                    text(
                        """
                        INSERT INTO omop_condition_occurrence (
                            person_id, condition_concept_id, condition_concept_id_int,
                            condition_source_value, condition_start_date,
                            condition_type_concept_id, is_expected_baseline,
                            project_id, created_at
                        ) VALUES (
                            :person_id, :condition_concept_id, :condition_concept_id_int,
                            :condition_source_value, :condition_start_date,
                            :condition_type_concept_id, :is_expected_baseline,
                            :project_id, NOW()
                        )
                        ON CONFLICT (person_id, condition_source_value, condition_start_date)
                        WHERE condition_source_value IS NOT NULL AND condition_start_date IS NOT NULL
                        DO NOTHING
                        """
                    ),
                    payload,
                )
                if (r.rowcount or 0) > 0:
                    conditions += 1
            except Exception:
                exists = await conn.execute(
                    text(
                        """
                        SELECT 1 FROM omop_condition_occurrence
                        WHERE person_id = :person_id
                          AND condition_source_value = :condition_source_value
                          AND condition_start_date = :condition_start_date
                        LIMIT 1
                        """
                    ),
                    payload,
                )
                if exists.first() is None:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO omop_condition_occurrence (
                                person_id, condition_concept_id, condition_concept_id_int,
                                condition_source_value, condition_start_date,
                                condition_type_concept_id, is_expected_baseline,
                                project_id, created_at
                            ) VALUES (
                                :person_id, :condition_concept_id, :condition_concept_id_int,
                                :condition_source_value, :condition_start_date,
                                :condition_type_concept_id, :is_expected_baseline,
                                :project_id, NOW()
                            )
                            """
                        ),
                        payload,
                    )
                    conditions += 1

    return {"persons": persons, "drugs": drugs, "conditions": conditions}


async def ingest_faers(
    *,
    faers_json: Optional[Path] = None,
    database_url: Optional[str] = None,
    limit: int = 50_000,
    batch_size: int = DEFAULT_BATCH,
    project_id: Optional[int] = None,
    force_fixture: bool = False,
) -> dict[str, Any]:
    load_dotenv()
    raw = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise EnvironmentError("DATABASE_URL is required for FAERS ingest")

    engine = create_async_engine(_to_async_url(raw), pool_pre_ping=True)
    totals = {"persons": 0, "drugs": 0, "conditions": 0, "dropped": 0, "batches": 0}
    mode = "fixture"

    try:
        async with engine.begin() as conn:
            await _ensure_schema(conn)
            resolver = ConceptResolver()
            await resolver.load(conn)

        def _source() -> Iterator[dict]:
            nonlocal mode
            if force_fixture:
                mode = "fixture"
                if _FIXTURE.exists():
                    yield from _iter_json_file_events(_FIXTURE)
                return
            if faers_json and Path(faers_json).is_file():
                mode = "json_file"
                yield from _iter_json_file_events(Path(faers_json))
                return
            if faers_json and Path(faers_json).is_dir():
                mode = "json_dir"
                for fp in sorted(Path(faers_json).glob("*.json")):
                    yield from _iter_json_file_events(fp)
                return
            # Live API then fixture fallback
            mode = "openfda"
            saw = False
            for ev in _iter_openfda_api(limit=limit):
                saw = True
                yield ev
            if not saw:
                mode = "fixture"
                if _FIXTURE.exists():
                    yield from _iter_json_file_events(_FIXTURE)

        processed = 0
        for batch in _batched(_source(), batch_size):
            if processed >= limit:
                break
            if processed + len(batch) > limit:
                batch = batch[: max(0, limit - processed)]
            transformed: List[dict[str, Any]] = []
            for event in batch:
                row = _transform_event(event, resolver, project_id=project_id)
                if row is None:
                    totals["dropped"] += 1
                else:
                    transformed.append(row)
            async with engine.begin() as conn:
                stats = await _flush_batch(conn, transformed)
            for k, v in stats.items():
                totals[k] = totals.get(k, 0) + v
            totals["batches"] += 1
            processed += len(batch)
            LOGGER.info(
                "Batch %d — events=%d persons+%d drugs+%d conditions+%d dropped=%d",
                totals["batches"],
                len(batch),
                stats["persons"],
                stats["drugs"],
                stats["conditions"],
                totals["dropped"],
            )

        return {
            "mode": mode,
            "batch_size": batch_size,
            "limit": limit,
            "events_processed": processed,
            **totals,
        }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Stream FAERS/openFDA JSON to OMOP staging")
    parser.add_argument("--faers-json", type=Path, default=None, help="File or directory of FAERS JSON")
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--force-fixture", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)
    try:
        result = asyncio.run(
            ingest_faers(
                faers_json=args.faers_json,
                database_url=args.database_url,
                limit=args.limit,
                batch_size=args.batch_size,
                project_id=args.project_id,
                force_fixture=args.force_fixture,
            )
        )
        LOGGER.info("FAERS ingest complete: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("ingest_faers failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
