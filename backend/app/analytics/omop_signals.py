"""OMOP-backed adverse-event retrieval for a drug RxCUI (Module 3).

Joins DRUG_EXPOSURE → PERSON → CONDITION_OCCURRENCE via CONCEPT, then computes
PRR/ROR (Haldane-Anscombe) over the observed (drug, condition) pairs. Falls back
to the VigilAI Signal table when OMOP staging is thin (offline-first).
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..analytics.disproportionality import compute_signals
from ..db.omop_concept_seed import find_drug_concepts_for_rxcui, seed_concepts_from_surrogates
from ..db.omop_models import (
    OMOP_CDM_VERSION,
    OMOP_DISCLAIMER,
    CONDITION_TYPE_PRIMARY_AE,
    Concept,
    ConditionOccurrence,
    DrugExposure,
)
from ..models import Signal
from ..nlp.ontology import aliases_for_product, resolve_product
from ..search_engine import resolve_brand_to_chemical

logger = logging.getLogger("vigilai.omop.signals")


class OmopAeRow(BaseModel):
    condition_concept_id: Optional[str] = None
    condition_name: str
    meddra_pt: Optional[str] = None
    n_persons: int = 0
    n_occurrences: int = 0
    prr: Optional[float] = None
    ror: Optional[float] = None
    chi_square: Optional[float] = None
    eb05: Optional[float] = None
    ic025: Optional[float] = None
    strength: Optional[str] = None
    sdr_flag: bool = False


class OmopSignalsResponse(BaseModel):
    rxcui: str
    resolved_rxcui: Optional[str] = None
    drug_name: Optional[str] = None
    ingredient_rxcuis: List[str] = Field(default_factory=list)
    concept_ids: List[int] = Field(default_factory=list)
    comparison_brands: List[str] = Field(default_factory=list)
    adverse_events: List[OmopAeRow] = Field(default_factory=list)
    n_exposures: int = 0
    n_persons: int = 0
    source: str = "omop"
    cdm_version: str = OMOP_CDM_VERSION
    notes: List[str] = Field(default_factory=list)
    disclaimer: str = OMOP_DISCLAIMER


def _normalize_rxcui_query(rxcui: str, db: Session) -> Tuple[str, Optional[object], List[str]]:
    """Return (canonical_rxcui, BrandChemicalResolution|None, search keys)."""
    raw = (rxcui or "").strip()
    resolution = resolve_brand_to_chemical(raw, online=False)
    keys: Set[str] = {raw.lower()}
    canonical = raw
    brands: List[str] = []

    if resolution.matched:
        if resolution.brand_rxcui:
            canonical = resolution.brand_rxcui
            keys.add(resolution.brand_rxcui.lower())
        if resolution.brand_name:
            keys.add(resolution.brand_name.lower())
            brands.append(resolution.brand_name)
        for ing in resolution.ingredients or []:
            if ing.rxcui:
                keys.add(ing.rxcui.lower())
                if not resolution.brand_rxcui:
                    canonical = ing.rxcui
            if ing.generic:
                keys.add(ing.generic.lower())
                keys |= {a.lower() for a in aliases_for_product(ing.generic)}
        brands.extend(resolution.subset_brands or [])
    else:
        # Treat path param as ingredient RxCUI / generic
        concept = resolve_product(raw)
        if concept.preferred_generic:
            keys.add(concept.preferred_generic.lower())
            keys |= {a.lower() for a in aliases_for_product(concept.preferred_generic)}
        if concept.rxcui:
            keys.add(f"rxnorm:{concept.rxcui}".lower())
            keys.add(str(concept.rxcui).lower())
            canonical = f"RXNORM:{concept.rxcui}" if not str(concept.rxcui).upper().startswith("RX") else str(concept.rxcui)

    # CONCEPT vocabulary matches
    for c in find_drug_concepts_for_rxcui(db, raw):
        keys.add((c.concept_code or "").lower())
        keys.add((c.concept_name or "").lower())
        if c.concept_id:
            keys.add(str(c.concept_id))

    return canonical, resolution if resolution.matched else None, sorted(k for k in keys if k)


def _omop_pairs_for_keys(
    db: Session,
    keys: Set[str],
    *,
    project_id: Optional[int] = None,
) -> Tuple[List[Tuple[str, str]], int, int, List[int]]:
    """Return (pairs, n_exposures, n_persons, concept_ids)."""
    if not keys:
        return [], 0, 0, []

    concepts = (
        db.query(Concept)
        .filter(Concept.domain_id == "Drug")
        .all()
    )
    matched_concept_ids = [
        c.concept_id
        for c in concepts
        if (c.concept_code or "").lower() in keys or (c.concept_name or "").lower() in keys
    ]

    dq = db.query(DrugExposure)
    if project_id is not None:
        dq = dq.filter(DrugExposure.project_id == project_id)
    exposures: List[DrugExposure] = []
    for row in dq.all():
        concept = (row.drug_concept_id or "").strip().lower()
        source = (row.drug_source_value or "").strip().lower()
        cid_int = row.drug_concept_id_int
        if cid_int and cid_int in matched_concept_ids:
            exposures.append(row)
        elif concept in keys or source in keys:
            exposures.append(row)
        elif any(k and (k in concept or k in source) for k in keys):
            exposures.append(row)

    if not exposures:
        return [], 0, 0, matched_concept_ids

    person_ids = {e.person_id for e in exposures}
    cq = db.query(ConditionOccurrence).filter(
        ConditionOccurrence.person_id.in_(person_ids),
        ConditionOccurrence.condition_type_concept_id == CONDITION_TYPE_PRIMARY_AE,
    )
    if project_id is not None:
        cq = cq.filter(ConditionOccurrence.project_id == project_id)

    # Map person → drug surface for pair labelling
    person_drug: Dict[int, str] = {}
    for e in exposures:
        person_drug[e.person_id] = (e.drug_source_value or e.drug_concept_id or "drug").strip()

    pairs: List[Tuple[str, str]] = []
    for cond in cq.all():
        drug = person_drug.get(cond.person_id) or "drug"
        event = (cond.condition_source_value or cond.condition_concept_id or "").strip()
        if event:
            pairs.append((drug, event))
    return pairs, len(exposures), len(person_ids), matched_concept_ids


def _signal_fallback_pairs(
    db: Session,
    keys: Set[str],
    *,
    project_id: Optional[int] = None,
) -> List[Tuple[str, str]]:
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    pairs: List[Tuple[str, str]] = []
    for sig in q.all():
        drug = (sig.drug or "").strip().lower()
        if drug not in keys and not any(k in drug for k in keys if len(k) > 3):
            # also match preferred generic aliases already in keys
            continue
        event = (sig.meddra_pt or sig.symptom or "").strip()
        if not event:
            continue
        count = max(1, int(sig.post_count or 1))
        pairs.extend([(sig.drug, event)] * count)
    return pairs


def get_signals_for_rxcui(
    db: Session,
    rxcui: str,
    *,
    project_id: Optional[int] = None,
    ensure_concepts: bool = True,
) -> OmopSignalsResponse:
    notes: List[str] = []
    if ensure_concepts:
        try:
            from ..database import init_db

            init_db()
        except Exception as exc:
            logger.debug("init_db during OMOP signals: %s", exc)
        try:
            n_concepts = db.query(Concept).count()
        except Exception:
            n_concepts = 0
            db.rollback()
        if n_concepts < 10:
            try:
                seeded = seed_concepts_from_surrogates(db)
                notes.append(
                    f"Seeded OMOP CONCEPT from RxE/MCN surrogates "
                    f"({seeded.get('drug_concepts')} drug, {seeded.get('condition_concepts')} condition)."
                )
            except Exception as exc:
                notes.append(f"Concept seed deferred: {exc}")
                db.rollback()

    canonical, resolution, key_list = _normalize_rxcui_query(rxcui, db)
    keys = set(key_list)

    pairs, n_exp, n_pers, concept_ids = _omop_pairs_for_keys(db, keys, project_id=project_id)
    source = "omop"
    if not pairs:
        pairs = _signal_fallback_pairs(db, keys, project_id=project_id)
        source = "signal_fallback"
        notes.append(
            "OMOP staging had no matching drug_exposure×condition_occurrence pairs; "
            "fell back to VigilAI Signal table (run POST /api/omop/sync)."
        )

    stats = compute_signals(pairs) if pairs else []
    # compute_signals returns list of dicts keyed by drug/event
    ae_rows: List[OmopAeRow] = []
    for row in stats:
        ae_rows.append(
            OmopAeRow(
                condition_concept_id=None,
                condition_name=row.get("symptom") or "",
                meddra_pt=row.get("symptom"),
                n_persons=int(row.get("post_count") or row.get("a") or 0),
                n_occurrences=int(row.get("post_count") or row.get("a") or 0),
                prr=row.get("prr"),
                ror=row.get("ror"),
                chi_square=row.get("chi_square") or row.get("chi2"),
                eb05=row.get("eb05"),
                ic025=row.get("ic025"),
                strength=row.get("strength"),
                sdr_flag=bool(row.get("sdr") or row.get("sdr_flag")),
            )
        )
    ae_rows.sort(key=lambda r: (-(r.prr or 0), -r.n_occurrences))

    drug_name = None
    ingredients: List[str] = []
    brands: List[str] = []
    if resolution is not None:
        drug_name = resolution.brand_name or resolution.query_term
        ingredients = [i.rxcui for i in (resolution.ingredients or []) if i.rxcui]
        brands = list(resolution.subset_brands or [])
        if resolution.brand_name and resolution.brand_name not in brands:
            brands = [resolution.brand_name, *brands]

    if not ae_rows:
        notes.append(
            "No adverse-event rows for this RxCUI. Try Janumet / RXNORM:VIG-6809 "
            "(metformin) after loading the PV demo pack and syncing OMOP."
        )

    return OmopSignalsResponse(
        rxcui=rxcui,
        resolved_rxcui=canonical,
        drug_name=drug_name,
        ingredient_rxcuis=ingredients,
        concept_ids=concept_ids,
        comparison_brands=brands,
        adverse_events=ae_rows,
        n_exposures=n_exp,
        n_persons=n_pers if n_pers else len({p[0] for p in pairs}),
        source=source,
        notes=notes,
    )
