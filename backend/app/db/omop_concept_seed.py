"""Seed / resolve OMOP CONCEPT rows from RxE + MCN + MedDRA surrogates."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from .omop_models import Concept

logger = logging.getLogger("vigilai.omop.concept")

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def _stable_concept_id(*parts: str) -> int:
    """Deterministic positive concept_id that fits signed 32-bit *and* BIGINT.

    Historical formula ``2e9 + (h % 700e6)`` reached ~2.7e9 and overflowed
    PostgreSQL INTEGER (max 2_147_483_647) — see NumericValueOutOfRange on
    Janumet seed. Range here: 1_100_000_000 .. 2_099_999_999.
    """
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return 1_100_000_000 + (int(digest[:8], 16) % 1_000_000_000)


def upsert_concept(
    db: Session,
    *,
    concept_code: str,
    concept_name: str,
    domain_id: str,
    vocabulary_id: str,
    concept_class_id: str = "Clinical Drug",
    standard_concept: str = "S",
) -> Concept:
    code = (concept_code or "").strip()
    if not code:
        raise ValueError("concept_code required")
    existing = (
        db.query(Concept)
        .filter(Concept.vocabulary_id == vocabulary_id, Concept.concept_code == code)
        .first()
    )
    if existing:
        if concept_name and existing.concept_name != concept_name:
            existing.concept_name = concept_name[:255]
        # Migrate pre-BIGINT hash overflows (e.g. 2535557769 for Janumet)
        if int(existing.concept_id) > 2_147_483_647:
            new_id = _stable_concept_id(vocabulary_id, code)
            if db.get(Concept, new_id) is None:
                payload = {
                    "concept_name": existing.concept_name,
                    "domain_id": existing.domain_id,
                    "vocabulary_id": existing.vocabulary_id,
                    "concept_class_id": existing.concept_class_id,
                    "standard_concept": existing.standard_concept,
                    "concept_code": existing.concept_code,
                    "valid_start_date": existing.valid_start_date,
                    "valid_end_date": existing.valid_end_date,
                    "invalid_reason": existing.invalid_reason,
                }
                db.delete(existing)
                db.flush()
                row = Concept(concept_id=new_id, **payload)
                db.add(row)
                db.flush()
                return row
        return existing
    row = Concept(
        concept_id=_stable_concept_id(vocabulary_id, code),
        concept_name=(concept_name or code)[:255],
        domain_id=domain_id,
        vocabulary_id=vocabulary_id,
        concept_class_id=concept_class_id,
        standard_concept=standard_concept,
        concept_code=code,
        valid_start_date=date(1970, 1, 1),
        valid_end_date=date(2099, 12, 31),
        invalid_reason=None,
    )
    # Handle rare hash collision on PK
    clash = db.get(Concept, row.concept_id)
    if clash and (clash.vocabulary_id, clash.concept_code) != (vocabulary_id, code):
        row.concept_id = _stable_concept_id(vocabulary_id, code, concept_name or "")
    db.add(row)
    db.flush()
    return row


def seed_concepts_from_surrogates(db: Session) -> dict:
    """Load RxE ingredients/brands + MCN clinical concepts into omop_concept."""
    n_drug = n_cond = 0

    rxe_path = DATA_ROOT / "search" / "rxe_extension_surrogate.json"
    if rxe_path.exists():
        payload = json.loads(rxe_path.read_text(encoding="utf-8"))
        brands = payload.get("brands") or {}
        if isinstance(brands, dict):
            brand_iter = brands.items()
        else:
            brand_iter = ((b.get("brand_name"), b) for b in brands)
        for brand_key, brand in brand_iter:
            if not isinstance(brand, dict):
                continue
            brand_code = str(brand.get("brand_rxcui") or "").strip()
            brand_name = str(brand.get("brand_name") or brand_key or brand_code)
            if brand_code:
                upsert_concept(
                    db,
                    concept_code=brand_code,
                    concept_name=brand_name,
                    domain_id="Drug",
                    vocabulary_id="RxNorm Extension",
                    concept_class_id="Branded Drug",
                )
                n_drug += 1
            for ing in brand.get("ingredients") or []:
                code = str(ing.get("rxcui") or "").strip()
                name = str(ing.get("generic") or code)
                if not code:
                    continue
                upsert_concept(
                    db,
                    concept_code=code,
                    concept_name=name,
                    domain_id="Drug",
                    vocabulary_id="RxNorm",
                    concept_class_id="Ingredient",
                )
                n_drug += 1

    mcn_path = DATA_ROOT / "normalization" / "umls_concept_catalog_surrogate.json"
    if mcn_path.exists():
        payload = json.loads(mcn_path.read_text(encoding="utf-8"))
        for concept in payload.get("concepts") or []:
            pt = concept.get("meddra_pt") or concept.get("preferred")
            cui = concept.get("cui") or pt
            if not pt:
                continue
            upsert_concept(
                db,
                concept_code=str(cui),
                concept_name=str(pt),
                domain_id="Condition",
                vocabulary_id="MedDRA",
                concept_class_id="PT",
            )
            n_cond += 1

    # Gender standards
    for cid, name in (
        (8507, "MALE"),
        (8532, "FEMALE"),
        (0, "UNKNOWN"),
    ):
        if db.get(Concept, cid) is None:
            db.add(
                Concept(
                    concept_id=cid,
                    concept_name=name,
                    domain_id="Gender",
                    vocabulary_id="SNOMED",
                    concept_class_id="Gender",
                    standard_concept="S",
                    concept_code=str(cid),
                    valid_start_date=date(1970, 1, 1),
                    valid_end_date=date(2099, 12, 31),
                )
            )

    db.commit()
    return {"drug_concepts": n_drug, "condition_concepts": n_cond}


def find_drug_concepts_for_rxcui(db: Session, rxcui: str) -> list[Concept]:
    """Match CONCEPT rows for a raw RxCUI / RxE code / numeric fragment."""
    raw = (rxcui or "").strip()
    if not raw:
        return []
    variants = {raw, raw.upper(), raw.lower()}
    # Strip common prefixes
    for prefix in ("RXNORM:", "RXCUI:", "RXE:", "rxnorm:", "rxcui:"):
        if raw.upper().startswith(prefix.upper()):
            variants.add(raw[len(prefix):].strip())
            variants.add(raw.upper())
            variants.add(f"RXNORM:{raw[len(prefix):].strip()}")
            variants.add(f"RXE:{raw[len(prefix):].strip()}")
    # Also try with/without VIG-
    bare = raw
    for p in ("RXNORM:", "RXCUI:", "RXE:"):
        if bare.upper().startswith(p):
            bare = bare[len(p):]
    variants.add(bare)
    variants.add(f"RXNORM:{bare}")
    variants.add(f"RXNORM:VIG-{bare}" if not bare.upper().startswith("VIG-") else f"RXNORM:{bare}")
    variants.add(f"RXE:{bare}")

    rows = (
        db.query(Concept)
        .filter(Concept.domain_id == "Drug")
        .filter(Concept.concept_code.in_(list(variants)))
        .all()
    )
    if rows:
        return rows
    # Fuzzy: concept_code endswith bare numeric / token
    token = bare.replace("VIG-", "").strip()
    if len(token) >= 3:
        return (
            db.query(Concept)
            .filter(Concept.domain_id == "Drug")
            .filter(Concept.concept_code.ilike(f"%{token}%"))
            .limit(20)
            .all()
        )
    return []
