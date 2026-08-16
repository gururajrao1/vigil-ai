"""Streaming openFDA / FAERS JSON → OMOP + dashboard posts.

Processes quarterly FAERS JSON dumps or live openFDA ``/drug/event`` payloads in
batches of 5,000 events. Maps drug names and MedDRA PTs to ``omop_concept``
BIGINT identifiers, then bridges each ICSR into ``raw_posts`` /
``processed_posts`` (same ``faers_{safetyreportid}`` keys as live FAERS crawl)
so Overview **Posts ingested** reflects bulk ETL.

Usage::

    python -m app.etl_pipeline.ingest_faers --faers-json /data/faers_q.json
    python -m app.etl_pipeline.ingest_faers --limit 5000 --recompute-signals
    python -m app.etl_pipeline.ingest_faers --skip-posts   # OMOP only
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db.pg_url import create_async_engine_normalized

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
    """Return a compact name set for OMOP drug_source_value rows.

    openFDA ``openfda.brand_name`` / ``generic_name`` arrays can be huge; we keep
    medicinalproduct plus at most one generic and one brand to avoid
    combinatorial explosion during bulk FAERS loads.
    """
    names: List[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        v = str(raw or "").strip()
        if not v:
            return
        key = v.lower()
        if key in seen:
            return
        seen.add(key)
        names.append(v)

    _add(drug.get("medicinalproduct"))
    openfda = drug.get("openfda") or {}
    for key in ("generic_name", "brand_name"):
        vals = openfda.get(key) or []
        if isinstance(vals, str):
            vals = [vals]
        if vals:
            _add(vals[0])
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
    """Bring legacy ``omop_*`` staging tables up to Phase-2 FAERS expectations.

    Neon / older VigilAI DBs often lack ``person_source_value``, BIGINT ids, and
    ``*_concept_id_int`` columns. Prefer AUTOCOMMIT for this function (see
    ``ingest_faers``). Each statement is isolated with a SAVEPOINT when running
    inside a transaction so one failure does not abort the rest.
    """
    statements = [
        # --- person ---
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS person_source_value VARCHAR(50)",
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS gender_source_value VARCHAR(50)",
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS ethnicity_concept_id BIGINT DEFAULT 0",
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS author_hash VARCHAR(64)",
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS project_id INTEGER",
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS source_raw_id INTEGER",
        "ALTER TABLE IF EXISTS omop_person ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()",
        "ALTER TABLE IF EXISTS omop_person ALTER COLUMN person_id TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_person ALTER COLUMN gender_concept_id TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_person ALTER COLUMN race_concept_id TYPE BIGINT",
        # --- drug_exposure ---
        "ALTER TABLE IF EXISTS omop_drug_exposure ADD COLUMN IF NOT EXISTS drug_concept_id_int BIGINT",
        "ALTER TABLE IF EXISTS omop_drug_exposure ADD COLUMN IF NOT EXISTS drug_source_value VARCHAR(256)",
        "ALTER TABLE IF EXISTS omop_drug_exposure ADD COLUMN IF NOT EXISTS project_id INTEGER",
        "ALTER TABLE IF EXISTS omop_drug_exposure ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()",
        "ALTER TABLE IF EXISTS omop_drug_exposure ALTER COLUMN person_id TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_drug_exposure ALTER COLUMN drug_concept_id_int TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_drug_exposure ALTER COLUMN drug_type_concept_id TYPE BIGINT",
        # --- condition_occurrence ---
        "ALTER TABLE IF EXISTS omop_condition_occurrence ADD COLUMN IF NOT EXISTS condition_concept_id_int BIGINT",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ADD COLUMN IF NOT EXISTS condition_source_value VARCHAR(256)",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ADD COLUMN IF NOT EXISTS is_expected_baseline BOOLEAN DEFAULT FALSE",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ADD COLUMN IF NOT EXISTS project_id INTEGER",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ALTER COLUMN person_id TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ALTER COLUMN condition_concept_id_int TYPE BIGINT",
        "ALTER TABLE IF EXISTS omop_condition_occurrence ALTER COLUMN condition_type_concept_id TYPE BIGINT",
        # --- concept PK widen (Athena / RxNorm Extension) ---
        "ALTER TABLE IF EXISTS omop_concept ALTER COLUMN concept_id TYPE BIGINT",
        # --- idempotency indexes (skip silently if legacy duplicates exist) ---
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
    # Detect whether we are already in a transaction (savepoint) or AUTOCOMMIT.
    in_txn = conn.in_transaction()
    for sql in statements:
        try:
            if in_txn:
                async with conn.begin_nested():
                    await conn.execute(text(sql))
            else:
                await conn.execute(text(sql))
        except Exception as exc:  # noqa: BLE001 — soft-fail per statement
            LOGGER.debug("Schema ensure skip: %s (%s)", sql.strip()[:72], exc)


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


def _event_to_faers_post(event: dict) -> Optional[dict[str, Any]]:
    """Build a dashboard ``raw_posts`` dict from an openFDA/FAERS ICSR event.

    Matches ``crawl_faers`` external_id / platform so live + bulk ETL share one
    dedupe key. Body is drugs + MedDRA PTs only (no patient identifiers).
    """
    safety = str(event.get("safetyreportid") or "").strip()
    if not safety:
        safety = hashlib.sha1(repr(event).encode("utf-8")).hexdigest()[:16]

    patient = event.get("patient") or {}
    if not isinstance(patient, dict):
        return None

    drug_names: List[str] = []
    for drug in patient.get("drug") or []:
        if not isinstance(drug, dict):
            continue
        for name in _drug_names(drug):
            titled = name.title()
            if titled and titled.lower() not in {n.lower() for n in drug_names}:
                drug_names.append(titled)

    reaction_terms: List[str] = []
    for reaction in patient.get("reaction") or []:
        if not isinstance(reaction, dict):
            continue
        pt = (reaction.get("reactionmeddrapt") or "").strip()
        if pt and pt.lower() not in {r.lower() for r in reaction_terms}:
            reaction_terms.append(pt)

    if not drug_names or not reaction_terms:
        return None

    drug_str = ", ".join(drug_names[:3])
    rx_str = ", ".join(reaction_terms[:5])
    receive_date = str(event.get("receiptdate") or event.get("receivedate") or "")
    body = (
        f"FDA adverse event report: {drug_str} associated with {rx_str}. "
        f"Serious report received {receive_date or 'unknown date'}."
    )
    if str(event.get("serious") or "") == "1":
        body += " Serious case."

    posted = datetime.utcnow()
    recv = _parse_date(receive_date)
    if recv is not None:
        posted = datetime.combine(recv, datetime.min.time())

    country = str(event.get("occurcountry") or "").strip().upper()
    try:
        from ..ingestion.sources import _country_to_region

        region = _country_to_region(country)
    except Exception:
        region = "North America" if country in {"", "US"} else "Global"

    return {
        "external_id": f"faers_{safety}",
        "platform": "faers",
        "product_type": "drug",
        "url": (
            "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
            f"?event=reportsSearch.process&query={safety}"
        ),
        "author": f"faers:{safety}",
        "title": f"FAERS: {drug_str[:60]} -> {rx_str[:60]}",
        "body": body,
        "region": region,
        "country": country or "US",
        "posted_at": posted,
        "faers_report_id": safety,
    }


def _flush_posts_sync(
    posts: Sequence[dict[str, Any]],
    *,
    project_id: Optional[int],
    db_ready: bool = False,
) -> int:
    """Bulk-insert FAERS ICSRs into ``raw_posts`` / ``processed_posts``.

    Regulatory ICSRs are already adverse-event narratives, so we set
    ``ae_flag=True`` with a deterministic gate trace instead of re-running the
    full social NLP stack (too slow for 10k+ bulk partitions). Dedupes on
    ``external_id`` (+ optional ``project_id``) like ``ingest_posts``.
    """
    if not posts:
        return 0

    import json as _json

    from ..database import SessionLocal, init_db
    from ..models import ProcessedPost, RawPost
    from ..privacy.hygiene import author_hash as hmac_author_hash

    if not db_ready:
        init_db()

    db = SessionLocal()
    try:
        ext_ids = [str(p.get("external_id") or "") for p in posts if p.get("external_id")]
        if not ext_ids:
            return 0

        existing_q = db.query(RawPost.external_id).filter(RawPost.external_id.in_(ext_ids))
        if project_id is not None:
            existing_q = existing_q.filter(RawPost.project_id == project_id)
        existing = {row[0] for row in existing_q.all()}

        inserted = 0
        for p in posts:
            ext = str(p.get("external_id") or "")
            if not ext or ext in existing:
                continue

            title = str(p.get("title") or "")[:512]
            body = str(p.get("body") or "")
            # Parse compact drug / PT lists from the synthetic narrative
            drugs: List[str] = []
            symptoms: List[str] = []
            if "FAERS:" in title and "->" in title:
                left, _, right = title.partition("->")
                drugs = [x.strip() for x in left.replace("FAERS:", "").split(",") if x.strip()]
                symptoms = [x.strip() for x in right.split(",") if x.strip()]
            elif "MAUDE:" in title and "->" in title:
                left, _, right = title.partition("->")
                drugs = [left.replace("MAUDE:", "").strip()]
                symptoms = [right.strip()] if right.strip() else ["device malfunction"]
            entities = {
                "drugs": drugs[:8],
                "symptoms": symptoms[:8],
                "conditions": symptoms[:8],
            }
            content_src = f"{title}\n{body}".strip().lower()
            content_hash = hashlib.sha256(content_src.encode("utf-8")).hexdigest()
            author = str(p.get("author") or ext)
            raw = RawPost(
                project_id=project_id if project_id is not None else p.get("project_id"),
                external_id=ext,
                platform=str(p.get("platform") or "faers"),
                product_type=str(p.get("product_type") or "drug"),
                url=p.get("url"),
                author_hash=hmac_author_hash(author),
                title=title,
                body=body,
                body_original=body,
                lang="en",
                lang_name="English",
                translated=False,
                region=str(p.get("region") or "Global"),
                country=p.get("country"),
                pii_found="[]",
                posted_at=p.get("posted_at") or datetime.utcnow(),
                processed=True,
                content_hash=content_hash,
                duplicate_count=0,
            )
            proc = ProcessedPost(
                raw=raw,
                entities_json=_json.dumps(entities),
                sentiment_label="NEGATIVE",
                sentiment_score=-0.85,
                negation_json=_json.dumps({s: False for s in symptoms[:8]}),
                ae_flag=True,
                ae_confidence=0.92,
                ae_reason="FAERS ICSR bulk bridge — regulatory AE narrative (drugs+PTs)",
                gate_trace_json=_json.dumps(
                    {
                        "source": "faers_etl_bridge",
                        "gates": {
                            "product": True,
                            "symptom": True,
                            "negative_sentiment": True,
                            "non_negated": True,
                        },
                    }
                ),
            )
            db.add(raw)
            db.add(proc)
            existing.add(ext)
            inserted += 1

        if inserted:
            db.commit()
        else:
            db.rollback()
        return inserted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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
    """Bulk-upsert a batch (minimize Neon round-trips)."""
    if not transformed:
        return {"persons": 0, "drugs": 0, "conditions": 0}

    persons_by_id: Dict[int, dict[str, Any]] = {}
    drugs: List[dict[str, Any]] = []
    conditions: List[dict[str, Any]] = []
    drug_keys: set[tuple] = set()
    cond_keys: set[tuple] = set()

    for row in transformed:
        p = row["person"]
        pid = int(p["person_id"])
        persons_by_id[pid] = p
        for d in row["drugs"]:
            payload = {**d, "person_id": pid}
            key = (
                pid,
                payload.get("drug_source_value"),
                payload.get("drug_exposure_start_date"),
            )
            if key in drug_keys:
                continue
            drug_keys.add(key)
            drugs.append(payload)
        for c in row["conditions"]:
            payload = {**c, "person_id": pid}
            key = (
                pid,
                payload.get("condition_source_value"),
                payload.get("condition_start_date"),
            )
            if key in cond_keys:
                continue
            cond_keys.add(key)
            conditions.append(payload)

    person_rows = list(persons_by_id.values())
    persons_inserted = 0
    if person_rows:
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
            person_rows,
        )
        persons_inserted = len(person_rows)

    drugs_inserted = 0
    if drugs:
        # Explicit casts avoid asyncpg AmbiguousParameterError across executemany
        # rows (text vs varchar / int vs null).
        await conn.execute(
            text(
                """
                INSERT INTO omop_drug_exposure (
                    person_id, drug_concept_id, drug_concept_id_int,
                    drug_source_value, drug_exposure_start_date,
                    drug_type_concept_id, project_id, created_at
                )
                SELECT
                    CAST(:person_id AS BIGINT),
                    CAST(:drug_concept_id AS VARCHAR),
                    CAST(:drug_concept_id_int AS BIGINT),
                    CAST(:drug_source_value AS VARCHAR),
                    CAST(:drug_exposure_start_date AS DATE),
                    CAST(:drug_type_concept_id AS BIGINT),
                    CAST(:project_id AS INTEGER),
                    NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM omop_drug_exposure e
                    WHERE e.person_id = CAST(:person_id AS BIGINT)
                      AND e.drug_source_value IS NOT DISTINCT FROM CAST(:drug_source_value AS VARCHAR)
                      AND e.drug_exposure_start_date IS NOT DISTINCT FROM CAST(:drug_exposure_start_date AS DATE)
                )
                """
            ),
            drugs,
        )
        # asyncpg executemany rowcount is often -1; report attempted unique rows.
        drugs_inserted = len(drugs)

    conditions_inserted = 0
    if conditions:
        await conn.execute(
            text(
                """
                INSERT INTO omop_condition_occurrence (
                    person_id, condition_concept_id, condition_concept_id_int,
                    condition_source_value, condition_start_date,
                    condition_type_concept_id, is_expected_baseline,
                    project_id, created_at
                )
                SELECT
                    CAST(:person_id AS BIGINT),
                    CAST(:condition_concept_id AS VARCHAR),
                    CAST(:condition_concept_id_int AS BIGINT),
                    CAST(:condition_source_value AS VARCHAR),
                    CAST(:condition_start_date AS DATE),
                    CAST(:condition_type_concept_id AS BIGINT),
                    CAST(:is_expected_baseline AS BOOLEAN),
                    CAST(:project_id AS INTEGER),
                    NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM omop_condition_occurrence e
                    WHERE e.person_id = CAST(:person_id AS BIGINT)
                      AND e.condition_source_value IS NOT DISTINCT FROM CAST(:condition_source_value AS VARCHAR)
                      AND e.condition_start_date IS NOT DISTINCT FROM CAST(:condition_start_date AS DATE)
                )
                """
            ),
            conditions,
        )
        conditions_inserted = len(conditions)

    return {
        "persons": persons_inserted,
        "drugs": drugs_inserted,
        "conditions": conditions_inserted,
    }


async def ingest_faers(
    *,
    faers_json: Optional[Path] = None,
    database_url: Optional[str] = None,
    limit: int = 50_000,
    batch_size: int = DEFAULT_BATCH,
    project_id: Optional[int] = None,
    force_fixture: bool = False,
    also_posts: bool = True,
    recompute_signals: bool = False,
) -> dict[str, Any]:
    load_dotenv()
    raw = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise EnvironmentError("DATABASE_URL is required for FAERS ingest")
    if raw.lower().startswith("sqlite"):
        raise EnvironmentError(
            "ingest_faers requires PostgreSQL (asyncpg). "
            "Set DATABASE_URL to a postgresql://… URL (Neon/Render/local), "
            "not sqlite."
        )
    # Guard against leftover placeholder URLs from docs / copy-paste
    low = raw.lower()
    if "://user:pass@" in low or "@host/" in low or "@host?" in low:
        raise EnvironmentError(
            "DATABASE_URL still looks like a placeholder (USER:PASS@HOST). "
            "Paste your real Neon/Render pooled URL, e.g. "
            "postgresql://…@ep-….neon.tech/neondb?sslmode=require"
        )

    engine = create_async_engine_normalized(raw)
    totals = {
        "persons": 0,
        "drugs": 0,
        "conditions": 0,
        "dropped": 0,
        "batches": 0,
        "posts": 0,
    }
    mode = "fixture"

    try:
        # DDL must not run inside a long interactive transaction — ALTER TYPE
        # takes AccessExclusiveLock and will hang behind any idle txn.
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await _ensure_schema(conn)

        async with engine.begin() as conn:
            resolver = ConceptResolver()
            await resolver.load(conn)

        if also_posts:
            # Warm sync schema once — avoid migrate_schema on every batch.
            from ..database import init_db as _init_sync_db

            await asyncio.to_thread(_init_sync_db)
            LOGGER.info("Sync schema ready for FAERS->posts bridge")

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
            post_dicts: List[dict[str, Any]] = []
            for event in batch:
                row = _transform_event(event, resolver, project_id=project_id)
                if row is None:
                    totals["dropped"] += 1
                else:
                    transformed.append(row)
                    if also_posts:
                        post = _event_to_faers_post(event)
                        if post is not None:
                            if project_id is not None:
                                post["project_id"] = project_id
                            post_dicts.append(post)
            async with engine.begin() as conn:
                stats = await _flush_batch(conn, transformed)
            for k, v in stats.items():
                totals[k] = totals.get(k, 0) + v
            if also_posts and post_dicts:
                try:
                    n_posts = await asyncio.to_thread(
                        _flush_posts_sync,
                        post_dicts,
                        project_id=project_id,
                        db_ready=True,
                    )
                    totals["posts"] += n_posts
                except Exception as exc:  # noqa: BLE001
                    LOGGER.exception("FAERS→posts bridge failed (OMOP batch kept): %s", exc)
            totals["batches"] += 1
            processed += len(batch)
            LOGGER.info(
                "Batch %d — events=%d persons+%d drugs+%d conditions+%d posts+%d dropped=%d",
                totals["batches"],
                len(batch),
                stats["persons"],
                stats["drugs"],
                stats["conditions"],
                totals["posts"],
                totals["dropped"],
            )

        if recompute_signals and also_posts and totals["posts"] > 0:
            try:
                from ..database import SessionLocal, init_db
                from ..pipeline import recompute_signals as _recompute

                init_db()
                db = SessionLocal()
                try:
                    sig = await asyncio.to_thread(
                        lambda: _recompute(db, project_id=project_id)
                    )
                    totals["signals_recomputed"] = sig
                    LOGGER.info("recompute_signals after FAERS posts: %s", sig)
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("recompute_signals skipped: %s", exc)

        return {
            "mode": mode,
            "batch_size": batch_size,
            "limit": limit,
            "events_processed": processed,
            "also_posts": also_posts,
            **totals,
        }
    finally:
        await engine.dispose()


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Stream FAERS/openFDA JSON to OMOP staging (+ dashboard posts)"
    )
    parser.add_argument("--faers-json", type=Path, default=None, help="File or directory of FAERS JSON")
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--force-fixture", action="store_true")
    parser.add_argument(
        "--skip-posts",
        action="store_true",
        help="OMOP only — do not bridge into raw_posts / Overview post counts",
    )
    parser.add_argument(
        "--recompute-signals",
        action="store_true",
        help="After posts bridge, rebuild Signal rows from AE-flagged posts",
    )
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
                also_posts=not args.skip_posts,
                recompute_signals=args.recompute_signals,
            )
        )
        LOGGER.info("FAERS ingest complete: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("ingest_faers failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
