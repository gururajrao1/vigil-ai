"""Module 3 — OMOP CDM models + /api/v1/signals/{rxcui}."""
from __future__ import annotations

from app.analytics.omop_signals import get_signals_for_rxcui
from app.database import SessionLocal, init_db
from app.db.omop_concept_seed import seed_concepts_from_surrogates
from app.db.omop_models import (
    OMOP_CDM_VERSION,
    Concept,
    ConditionOccurrence,
    DrugExposure,
    Person,
)


def setup_function():
    init_db()


def test_omop_models_map_cdm_tables():
    assert Concept.__tablename__ == "omop_concept"
    assert Person.__tablename__ == "omop_person"
    assert DrugExposure.__tablename__ == "omop_drug_exposure"
    assert ConditionOccurrence.__tablename__ == "omop_condition_occurrence"
    assert OMOP_CDM_VERSION == "5.4"


def test_seed_concepts_from_rxe_and_mcn():
    db = SessionLocal()
    try:
        out = seed_concepts_from_surrogates(db)
        assert out["drug_concepts"] >= 5
        assert out["condition_concepts"] >= 5
        janumet = (
            db.query(Concept)
            .filter(Concept.concept_code == "RXE:VIG-806423")
            .first()
        )
        assert janumet is not None
        assert janumet.domain_id == "Drug"
        metformin = (
            db.query(Concept)
            .filter(Concept.concept_code == "RXNORM:VIG-6809")
            .first()
        )
        assert metformin is not None
        assert "metformin" in (metformin.concept_name or "").lower()
    finally:
        db.close()


def test_signals_by_rxcui_returns_pydantic_payload():
    db = SessionLocal()
    try:
        seed_concepts_from_surrogates(db)
        payload = get_signals_for_rxcui(db, "Janumet", ensure_concepts=False)
        dumped = payload.model_dump()
        assert dumped["rxcui"] == "Janumet"
        assert dumped["cdm_version"] == "5.4"
        assert "adverse_events" in dumped
        assert dumped["resolved_rxcui"]
        # Offline-first: may be omop or signal_fallback depending on staging fill
        assert dumped["source"] in {"omop", "signal_fallback"}
    finally:
        db.close()


def test_v1_route_registered():
    from fastapi.testclient import TestClient
    from app.main import app

    init_db()
    client = TestClient(app)
    res = client.get("/api/v1/signals/Janumet")
    assert res.status_code == 200
    body = res.json()
    assert body["rxcui"] == "Janumet"
    assert isinstance(body["adverse_events"], list)
