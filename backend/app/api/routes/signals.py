"""Module 3 — OMOP-driven signals by RxCUI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...analytics.omop_signals import OmopSignalsResponse, get_signals_for_rxcui
from ...database import get_db
from ...db.omop_concept_seed import seed_concepts_from_surrogates
from ...projects.scope import current_project_id

router = APIRouter(tags=["omop-signals"])


@router.get("/signals/{rxcui}", response_model=OmopSignalsResponse)
async def get_omop_signals_by_rxcui(
    rxcui: str,
    db: Session = Depends(get_db),
):
    """Retrieve adverse events linked to a generic/brand drug via OMOP CDM v5.4.

    Resolves ``rxcui`` through the CONCEPT vocabulary (RxNorm / RxE surrogates),
    joins ``drug_exposure`` → ``person`` → ``condition_occurrence``, and returns
    PRR/ROR disproportionality rows (Pydantic v2). Offline-first: falls back to
    the VigilAI Signal table when OMOP staging is empty.
    """
    term = (rxcui or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="rxcui is required")
    return get_signals_for_rxcui(
        db,
        term,
        project_id=current_project_id(),
        ensure_concepts=True,
    )


@router.post("/omop/concepts/seed")
async def seed_omop_concepts(db: Session = Depends(get_db)):
    """Upsert CONCEPT rows from RxE + MCN + gender surrogates."""
    return seed_concepts_from_surrogates(db)
