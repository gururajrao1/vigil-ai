"""Signals dashboard API — Omni-Search resolution + PRR/ROR disproportionality.

``GET /api/v1/signals/{query}`` resolves free text (brand, misspelling, or RxCUI)
through ``OmniSearchService``, then scores co-reported adverse events via
``calculate_prr_ror`` against ``omop_signal_summary``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.omop_concept_seed import seed_concepts_from_surrogates
from ...nlp.omni_search_service import OmniSearchHit, OmniSearchService
from ..deps import get_async_db
from ..services.statistics import (
    AeDisproportionality,
    DrugDisproportionalityReport,
    calculate_prr_ror,
)

LOGGER = logging.getLogger("vigilai.api.signals")

router = APIRouter(tags=["omop-signals"])


class ResolvedDrugMetadata(BaseModel):
    query: str
    concept_id: int
    concept_name: Optional[str] = None
    rxcui: Optional[str] = None
    vocabulary_id: Optional[str] = None
    brand_names: List[str] = Field(default_factory=list)
    active_ingredients: List[str] = Field(default_factory=list)
    atc_code: Optional[str] = None
    match_method: str = "unmatched"
    confidence: float = 0.0


class SignalAeRow(BaseModel):
    """Adverse-event row for Detect / Omni-Search consumers."""

    condition_concept_id: Optional[str] = None
    condition_name: Optional[str] = None
    meddra_pt: Optional[str] = None
    n_persons: int = 0
    n_occurrences: int = 0
    prr: Optional[float] = None
    prr_ci_low: Optional[float] = None
    prr_ci_high: Optional[float] = None
    ror: Optional[float] = None
    ror_ci_low: Optional[float] = None
    ror_ci_high: Optional[float] = None
    chi_square: Optional[float] = None
    eb05: Optional[float] = None
    ic025: Optional[float] = None
    strength: Optional[str] = None
    sdr_flag: bool = False
    contingency_a: Optional[float] = None
    contingency_b: Optional[float] = None
    contingency_c: Optional[float] = None
    contingency_d: Optional[float] = None


class SignalsQueryResponse(BaseModel):
    """Phase 4 Omni-Search + disproportionality payload (frontend-compatible)."""

    query: str
    resolved: ResolvedDrugMetadata
    adverse_events: List[SignalAeRow] = Field(default_factory=list)
    disproportionality: Optional[DrugDisproportionalityReport] = None
    omni: Optional[OmniSearchHit] = None
    # Back-compat aliases used by SignalsView / OmopSignalsResponse consumers
    rxcui: str = ""
    resolved_rxcui: Optional[str] = None
    drug_name: Optional[str] = None
    ingredient_rxcuis: List[str] = Field(default_factory=list)
    concept_ids: List[int] = Field(default_factory=list)
    comparison_brands: List[str] = Field(default_factory=list)
    n_exposures: int = 0
    n_persons: int = 0
    source: str = "omop_signal_summary"
    cdm_version: str = "5.4"
    notes: List[str] = Field(default_factory=list)
    disclaimer: str = ""


def _ae_row(ev: AeDisproportionality) -> SignalAeRow:
    return SignalAeRow(
        condition_concept_id=str(ev.condition_concept_id),
        condition_name=ev.condition_name,
        meddra_pt=ev.meddra_pt or ev.condition_name,
        n_persons=ev.exposure_count,
        n_occurrences=ev.exposure_count,
        prr=ev.prr,
        prr_ci_low=ev.prr_ci_low,
        prr_ci_high=ev.prr_ci_high,
        ror=ev.ror,
        ror_ci_low=ev.ror_ci_low,
        ror_ci_high=ev.ror_ci_high,
        chi_square=ev.chi_square,
        strength=ev.strength,
        sdr_flag=ev.sdr_flag,
        contingency_a=ev.contingency.a,
        contingency_b=ev.contingency.b,
        contingency_c=ev.contingency.c,
        contingency_d=ev.contingency.d,
    )


def _legacy_ae_row(row: dict) -> SignalAeRow:
    return SignalAeRow(
        condition_concept_id=str(row.get("condition_concept_id") or "") or None,
        condition_name=row.get("condition_name"),
        meddra_pt=row.get("meddra_pt") or row.get("condition_name"),
        n_persons=int(row.get("n_persons") or 0),
        n_occurrences=int(row.get("n_occurrences") or 0),
        prr=row.get("prr"),
        ror=row.get("ror"),
        chi_square=row.get("chi_square"),
        eb05=row.get("eb05"),
        ic025=row.get("ic025"),
        strength=row.get("strength"),
        sdr_flag=bool(row.get("sdr_flag")),
    )


def _build_response(
    *,
    term: str,
    omni: OmniSearchHit,
    report: Optional[DrugDisproportionalityReport],
    ae_rows: List[SignalAeRow],
    notes: List[str],
    source: str,
) -> SignalsQueryResponse:
    concept_id = int(omni.concept_id or 0)
    resolved = ResolvedDrugMetadata(
        query=term,
        concept_id=concept_id,
        concept_name=omni.concept_name,
        rxcui=omni.rxcui,
        vocabulary_id=omni.vocabulary_id,
        brand_names=list(omni.brand_names or []),
        active_ingredients=list(omni.active_ingredients or []),
        atc_code=omni.atc_code,
        match_method=omni.match_method,
        confidence=float(omni.confidence or 0.0),
    )
    ingredient_rxcuis: List[str] = []
    if omni.drug_resolution is not None:
        ingredient_rxcuis = list(omni.drug_resolution.ingredient_rxcuis or [])

    n_exp = report.drug_total_exposures if report else sum(r.n_persons for r in ae_rows)
    return SignalsQueryResponse(
        query=term,
        resolved=resolved,
        adverse_events=ae_rows,
        disproportionality=report,
        omni=omni,
        rxcui=omni.rxcui or term,
        resolved_rxcui=omni.rxcui,
        drug_name=omni.concept_name,
        ingredient_rxcuis=ingredient_rxcuis,
        concept_ids=[concept_id] if concept_id else [],
        comparison_brands=list(omni.brand_names or []),
        n_exposures=n_exp,
        n_persons=n_exp,
        source=source,
        notes=notes,
    )


def _sync_legacy_payload(term: str, lookup: str) -> dict:
    """Module 3 sync OMOP / Signal-table path (psycopg2 / SQLite)."""
    from ...analytics.omop_signals import get_signals_for_rxcui
    from ...database import SessionLocal, init_db
    from ...projects.scope import current_project_id

    init_db()
    db = SessionLocal()
    try:
        result = get_signals_for_rxcui(
            db,
            lookup,
            project_id=current_project_id(),
            ensure_concepts=True,
        )
        return result.model_dump() if hasattr(result, "model_dump") else dict(result)
    finally:
        db.close()


@router.get("/signals/{query}", response_model=SignalsQueryResponse)
async def get_signals_by_query(
    query: str,
    db: Optional[AsyncSession] = Depends(get_async_db),
    min_count: int = Query(1, ge=1, le=100, description="Minimum A-cell count"),
) -> SignalsQueryResponse:
    """Resolve ``query`` via Omni-Search, then return AEs sorted by PRR.

    Raises **404** when the string cannot be mapped to a drug OMOP concept.
    Empty AE lists (thin matview) return **200** with teaching notes — not an error.
    """
    term = (query or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="query is required")

    notes: List[str] = []
    omni: Optional[OmniSearchHit] = None

    try:
        service = OmniSearchService(session=db)
        omni = await service.search(term)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("OmniSearchService failed for %r: %s — retry offline", term, exc)
        try:
            omni = await OmniSearchService(session=None).search(term)
            notes.append(f"Omni-Search used offline fallback ({type(exc).__name__}).")
        except Exception as exc2:  # noqa: BLE001
            LOGGER.exception("OmniSearchService offline fallback failed for %r", term)
            raise HTTPException(
                status_code=503,
                detail=f"Omni-Search resolver unavailable: {exc2}",
            ) from exc2

    assert omni is not None

    if not omni.matched or omni.concept_id is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Could not resolve '{term}' to a clinical OMOP concept. "
                "Try Janumet, sitagliptin, Ozempic, or a known MedDRA PT."
            ),
        )

    if omni.entity_kind == "adverse_event":
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{term}' resolved as an adverse event ({omni.preferred_term or omni.concept_name}), "
                "not a drug. Search a brand or INN (e.g. Janumet) for PRR/ROR tables."
            ),
        )

    concept_id = int(omni.concept_id)
    report: Optional[DrugDisproportionalityReport] = None
    ae_rows: List[SignalAeRow] = []
    source = "omop_signal_summary"

    if db is not None:
        try:
            report = await calculate_prr_ror(concept_id, db, min_count=min_count)
            ae_rows = [_ae_row(ev) for ev in report.adverse_events]
            source = report.source
            notes.extend(report.notes)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("calculate_prr_ror failed (%s) — sync legacy fallback", exc)
            notes.append(f"Matview PRR unavailable ({type(exc).__name__}); using sync OMOP path.")
            report = None

    if report is None or (db is None and not ae_rows):
        lookup = omni.rxcui or term
        try:
            legacy = await asyncio.to_thread(_sync_legacy_payload, term, lookup)
            ae_rows = [_legacy_ae_row(r) for r in (legacy.get("adverse_events") or [])]
            ae_rows.sort(
                key=lambda r: (r.prr or 0.0, r.n_persons or 0),
                reverse=True,
            )
            source = str(legacy.get("source") or "omop_sync_fallback")
            notes.extend(legacy.get("notes") or [])
            if legacy.get("drug_name") and not omni.concept_name:
                omni.concept_name = legacy.get("drug_name")
            if legacy.get("comparison_brands") and not omni.brand_names:
                omni.brand_names = list(legacy.get("comparison_brands") or [])
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Sync legacy signals fallback failed for %r", term)
            notes.append(f"Sync OMOP fallback failed: {exc}")

    notes.extend(omni.notes or [])
    if not ae_rows:
        notes.append(
            "Resolved drug has no co-reported AEs yet — "
            "run FAERS ingest / ``run_pipeline`` then refresh the matview."
        )

    try:
        return _build_response(
            term=term,
            omni=omni,
            report=report,
            ae_rows=ae_rows,
            notes=notes,
            source=source,
        )
    except Exception as exc:  # noqa: BLE001 — never return bare 500 without detail
        LOGGER.exception("Signals response build failed for %r", term)
        raise HTTPException(
            status_code=500,
            detail=f"Signals response serialization failed: {exc}",
        ) from exc


@router.post("/omop/concepts/seed")
async def seed_omop_concepts() -> dict:
    """Upsert CONCEPT rows from RxE + MCN + gender surrogates (sync seed helper)."""
    from ...database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        return seed_concepts_from_surrogates(db)
    finally:
        db.close()
