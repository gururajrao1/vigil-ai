"""openFDA FAERS → OMOP CDM staging (streaming / batched).

Targets the public openFDA drug/event JSON API (same payloads as open.fda.gov
FAERS exports). Processes results in page-sized batches to avoid OOM on large
quarterly dumps. Offline fallback: ``ingestion/fixtures/faers_bulk_sample.json``.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..db.omop_concept_seed import upsert_concept
from ..db.omop_models import (
    CONDITION_TYPE_PRIMARY_AE,
    ConditionOccurrence,
    DrugExposure,
    Person,
)

logger = logging.getLogger("vigilai.etl.faers")

_USER_AGENT = "VigilAI-ETL/1.0 (offline-first; research prototype)"
_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "ingestion"
    / "fixtures"
    / "faers_bulk_sample.json"
)
DEFAULT_BATCH = 50
OPENFDA_PAGE = 100


def _hash_person(safety_id: str) -> str:
    return hashlib.sha256(f"faers:{safety_id}".encode("utf-8")).hexdigest()[:32]


def _parse_date(raw: Any) -> Optional[date]:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    return None


def _iter_openfda_events(
    *,
    limit: int,
    page_size: int = OPENFDA_PAGE,
) -> Iterator[List[dict]]:
    """Yield event pages from openFDA; yields nothing if network unavailable."""
    try:
        import httpx
    except ImportError:
        return

    fetched = 0
    skip = 0
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": _USER_AGENT}) as client:
            while fetched < limit:
                n = min(page_size, limit - fetched)
                resp = client.get(
                    "https://api.fda.gov/drug/event.json",
                    params={"search": "serious:1", "limit": n, "skip": skip},
                )
                if resp.status_code != 200:
                    logger.info("openFDA FAERS HTTP %s — stopping live pull", resp.status_code)
                    break
                results = resp.json().get("results") or []
                if not results:
                    break
                yield results
                fetched += len(results)
                skip += len(results)
                if len(results) < n:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.info("openFDA FAERS unavailable (%s) — fixture fallback", exc)


def _fixture_events(limit: int) -> List[dict]:
    import json

    if not _FIXTURE.exists():
        return []
    rows = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    events: List[dict] = []
    for i, row in enumerate(rows[:limit]):
        drugs = row.get("drugs") or [row.get("drug") or "unknown"]
        reactions = row.get("reactions") or [row.get("reaction") or "adverse event"]
        events.append({
            "safetyreportid": (row.get("external_id") or f"fx-{i}").replace("faers_bulk:", ""),
            "receiptdate": (row.get("posted_at") or "")[:10].replace("-", ""),
            "patient": {
                "drug": [{"medicinalproduct": d} for d in drugs],
                "reaction": [{"reactionmeddrapt": r} for r in reactions],
            },
        })
    return events


def _flatten_event(event: dict) -> Tuple[str, List[str], List[str], Optional[date]]:
    safety = str(event.get("safetyreportid") or "").strip()
    if not safety:
        safety = hashlib.sha1(repr(event).encode("utf-8")).hexdigest()[:12]
    patient = event.get("patient") or {}
    drugs: List[str] = []
    for d in patient.get("drug") or []:
        name = (d.get("medicinalproduct") or "").strip()
        if not name:
            openfda = d.get("openfda") or {}
            generics = openfda.get("generic_name") or []
            if generics:
                name = str(generics[0])
        if name:
            drugs.append(name.title())
    reactions = [
        (r.get("reactionmeddrapt") or "").strip()
        for r in (patient.get("reaction") or [])
        if r.get("reactionmeddrapt")
    ]
    recv = _parse_date(event.get("receiptdate") or event.get("receivedate"))
    return safety, drugs, reactions, recv


def ingest_faers_to_omop(
    db: Session,
    *,
    project_id: Optional[int] = None,
    limit: int = 200,
    force_fixture: bool = False,
    batch_size: int = DEFAULT_BATCH,
) -> dict:
    """Stream FAERS events into OMOP person / drug_exposure / condition_occurrence."""
    inserted_persons = 0
    inserted_drugs = 0
    inserted_conditions = 0
    dropped = 0
    mode = "fixture"
    saw_live = False

    def _flush(batch: List[dict], source_mode: str) -> None:
        nonlocal inserted_persons, inserted_drugs, inserted_conditions, dropped
        for event in batch:
            try:
                safety, drugs, reactions, recv = _flatten_event(event)
                if not drugs or not reactions:
                    dropped += 1
                    continue
                author = _hash_person(safety)
                q = db.query(Person).filter(Person.author_hash == author)
                if project_id is not None:
                    q = q.filter(Person.project_id == project_id)
                person = q.first()
                if person is None:
                    person = Person(
                        author_hash=author,
                        person_source_value=f"faers:{safety}"[:50],
                        project_id=project_id,
                        gender_concept_id=0,
                    )
                    db.add(person)
                    db.flush()
                    inserted_persons += 1

                for drug_name in drugs[:8]:
                    concept = upsert_concept(
                        db,
                        concept_code=f"FAERS:{drug_name.upper()[:40]}",
                        concept_name=drug_name,
                        domain_id="Drug",
                        vocabulary_id="FAERS",
                        concept_class_id="Ingredient",
                    )
                    db.add(
                        DrugExposure(
                            person_id=person.person_id,
                            drug_concept_id=concept.concept_code,
                            drug_concept_id_int=concept.concept_id,
                            drug_source_value=drug_name[:256],
                            drug_exposure_start_date=recv or date.today(),
                            project_id=project_id,
                        )
                    )
                    inserted_drugs += 1

                for pt in reactions[:12]:
                    concept = upsert_concept(
                        db,
                        concept_code=f"MEDDRA_SUR:{pt.upper()[:40]}",
                        concept_name=pt.title(),
                        domain_id="Condition",
                        vocabulary_id="MedDRA",
                        concept_class_id="PT",
                    )
                    db.add(
                        ConditionOccurrence(
                            person_id=person.person_id,
                            condition_concept_id=concept.concept_code,
                            condition_concept_id_int=concept.concept_id,
                            condition_source_value=pt[:256],
                            condition_start_date=recv or date.today(),
                            condition_type_concept_id=CONDITION_TYPE_PRIMARY_AE,
                            is_expected_baseline=False,
                            project_id=project_id,
                        )
                    )
                    inserted_conditions += 1
                db.commit()
            except Exception as exc:  # noqa: BLE001 — keep batch alive
                db.rollback()
                dropped += 1
                logger.warning("FAERS row dropped (%s): %s", source_mode, exc)

    buffer: List[dict] = []
    if not force_fixture:
        for page in _iter_openfda_events(limit=limit):
            saw_live = True
            mode = "openfda"
            for event in page:
                buffer.append(event)
                if len(buffer) >= batch_size:
                    _flush(buffer, mode)
                    buffer = []
        if buffer:
            _flush(buffer, mode)
            buffer = []

    if not saw_live or (inserted_persons == 0 and inserted_drugs == 0):
        mode = "fixture"
        _flush(_fixture_events(limit), mode)

    return {
        "mode": mode,
        "persons": inserted_persons,
        "drug_exposures": inserted_drugs,
        "condition_occurrences": inserted_conditions,
        "dropped": dropped,
        "limit": limit,
        "batch_size": batch_size,
    }
