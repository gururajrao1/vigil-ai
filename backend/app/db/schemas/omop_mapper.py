"""Map VigilAI RawPost + ProcessedPost rows into OMOP CDM v5.4 staging tables."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ...analytics.risk_features import age_bracket, parse_age_years, parse_sex
from ...models import ProcessedPost, RawPost
from ...nlp.devices import is_known_device
from ...nlp.ontology import resolve_product
from .omop_cdm import (
    CONDITION_TYPE_COMORBIDITY,
    CONDITION_TYPE_PRIMARY_AE,
    GENDER_FEMALE,
    GENDER_MALE,
    GENDER_UNKNOWN,
    OmopConditionOccurrence,
    OmopDeviceExposure,
    OmopDrugExposure,
    OmopPerson,
    today_or,
)

logger = logging.getLogger("vigilai.omop")


def _gender_concept(sex: Optional[str]) -> int:
    s = (sex or "").upper()
    if s in ("M", "MALE"):
        return GENDER_MALE
    if s in ("F", "FEMALE"):
        return GENDER_FEMALE
    return GENDER_UNKNOWN


def _year_from_age(age_years: Optional[float], posted_at) -> Optional[int]:
    if age_years is None:
        return None
    try:
        y = int(posted_at.year) if posted_at else today_or(None).year
        return y - int(age_years)
    except Exception:
        return None


def _entities(processed: ProcessedPost) -> dict:
    try:
        return json.loads(processed.entities_json or "{}") or {}
    except Exception:
        return {}


def get_or_create_person(
    db: Session,
    *,
    author_hash: str,
    text: str,
    posted_at,
    project_id: Optional[int],
    source_raw_id: Optional[int],
) -> OmopPerson:
    if author_hash:
        existing = (
            db.query(OmopPerson)
            .filter(OmopPerson.author_hash == author_hash)
            .first()
        )
        if existing:
            return existing
    age = parse_age_years(text)
    sex = parse_sex(text)
    person = OmopPerson(
        gender_concept_id=_gender_concept(sex),
        year_of_birth=_year_from_age(age, posted_at),
        race_concept_id=0,
        location_id=None,
        author_hash=author_hash or f"anon-{source_raw_id}",
        project_id=project_id,
        source_raw_id=source_raw_id,
    )
    db.add(person)
    db.flush()
    return person


def map_processed_to_omop(
    db: Session,
    processed: ProcessedPost,
    raw: RawPost,
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """Project one AE/processed post into PERSON + exposures + conditions."""
    ents = _entities(processed)
    text = f"{raw.title or ''} {raw.body or ''}"
    person = get_or_create_person(
        db,
        author_hash=raw.author_hash or "",
        text=text,
        posted_at=raw.posted_at,
        project_id=raw.project_id,
        source_raw_id=raw.id,
    )
    start = today_or(raw.posted_at)
    n_drug = n_device = n_cond = 0

    for d in ents.get("drugs") or []:
        surface = (d.get("text") or d.get("normalized") or "").strip()
        if not surface:
            continue
        concept = resolve_product(d.get("normalized") or surface)
        concept_id = (
            concept.atc
            or (f"RXCUI:{concept.rxcui}" if concept.rxcui else None)
            or concept.concept_id
            or concept.preferred_generic
            or surface.lower()
        )
        is_device = bool(d.get("is_device") or d.get("product_type") == "device" or is_known_device(surface))
        if is_device:
            db.add(OmopDeviceExposure(
                person_id=person.person_id,
                device_concept_id=str(d.get("gmdn") or concept_id),
                device_exposure_start_date=start,
                unique_device_id=d.get("unique_device_id"),
                device_source_value=surface[:256],
                project_id=raw.project_id,
                source_raw_id=raw.id,
            ))
            n_device += 1
        else:
            db.add(OmopDrugExposure(
                person_id=person.person_id,
                drug_concept_id=str(concept_id)[:64],
                drug_exposure_start_date=start,
                drug_source_value=surface[:256],
                project_id=raw.project_id,
                source_raw_id=raw.id,
            ))
            n_drug += 1

    for s in ents.get("symptoms") or []:
        pt = (s.get("pt") or s.get("normalized") or s.get("text") or "").strip()
        if not pt:
            continue
        cui = s.get("cui") or ""
        concept_id = str(cui or pt)[:128]
        db.add(OmopConditionOccurrence(
            person_id=person.person_id,
            condition_concept_id=concept_id,
            condition_start_date=start,
            condition_type_concept_id=CONDITION_TYPE_PRIMARY_AE,
            condition_source_value=pt[:256],
            condition_status_source_value="ae",
            project_id=raw.project_id,
            source_raw_id=raw.id,
        ))
        n_cond += 1

    for c in ents.get("conditions") or []:
        label = (c.get("normalized") or c.get("text") or "").strip()
        if not label:
            continue
        db.add(OmopConditionOccurrence(
            person_id=person.person_id,
            condition_concept_id=str(c.get("cui") or label)[:128],
            condition_start_date=start,
            condition_type_concept_id=CONDITION_TYPE_COMORBIDITY,
            condition_source_value=label[:256],
            condition_status_source_value="comorbidity",
            project_id=raw.project_id,
            source_raw_id=raw.id,
        ))
        n_cond += 1

    if commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "person_id": person.person_id,
        "n_drug_exposure": n_drug,
        "n_device_exposure": n_device,
        "n_condition_occurrence": n_cond,
        "age_bracket": age_bracket(parse_age_years(text)),
        "gender_concept_id": person.gender_concept_id,
    }


def sync_omop_from_corpus(
    db: Session,
    *,
    project_id: Optional[int] = None,
    limit: int = 500,
    ae_only: bool = True,
) -> dict:
    """Backfill OMOP staging from existing processed posts (idempotent-ish).

    Skips raw_ids that already have drug/device/condition rows.
    """
    q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
    )
    if ae_only:
        q = q.filter(ProcessedPost.ae_flag.is_(True))
    if project_id is not None:
        q = q.filter(RawPost.project_id == project_id)

    # Already mapped raw ids
    seen_drugs = {r[0] for r in db.query(OmopDrugExposure.source_raw_id).distinct().all() if r[0]}
    seen_devs = {r[0] for r in db.query(OmopDeviceExposure.source_raw_id).distinct().all() if r[0]}
    seen = seen_drugs | seen_devs

    mapped = skipped = 0
    for processed, raw in q.order_by(ProcessedPost.id.desc()).limit(limit).all():
        if raw.id in seen:
            skipped += 1
            continue
        try:
            map_processed_to_omop(db, processed, raw, commit=True)
            mapped += 1
            seen.add(raw.id)
        except Exception:
            logger.debug("OMOP map failed raw_id=%s", raw.id, exc_info=True)
            db.rollback()
            skipped += 1

    return {
        "mapped": mapped,
        "skipped": skipped,
        "persons": db.query(OmopPerson).count(),
        "drug_exposures": db.query(OmopDrugExposure).count(),
        "device_exposures": db.query(OmopDeviceExposure).count(),
        "condition_occurrences": db.query(OmopConditionOccurrence).count(),
        "disclaimer": (
            "OMOP CDM v5.4 staging over social/ICSR text. Open concept surrogates — "
            "not a validated OMOP warehouse; not for clinical use."
        ),
    }
