"""ETL pipeline + BIGINT concept_id + MCN CADEC/SMM4H benchmark."""
from __future__ import annotations

from app.database import SessionLocal, init_db
from app.db.omop_concept_seed import _stable_concept_id, seed_concepts_from_surrogates
from app.db.omop_models import Concept, DrugConditionBaseline
from app.etl_pipeline import trigger_dataset_sync
from app.nlp.validation import run_mcn_benchmark


def setup_function():
    init_db()


def test_stable_concept_id_fits_signed_int32():
    cid = _stable_concept_id("RxNorm Extension", "RXE:VIG-806423")
    assert 1_100_000_000 <= cid <= 2_099_999_999
    assert cid <= 2_147_483_647


def test_seed_janumet_no_overflow():
    db = SessionLocal()
    try:
        out = seed_concepts_from_surrogates(db)
        assert out["drug_concepts"] >= 5
        janumet = (
            db.query(Concept)
            .filter(Concept.concept_code == "RXE:VIG-806423")
            .first()
        )
        assert janumet is not None
        assert janumet.concept_id <= 2_147_483_647
    finally:
        db.close()


def test_faers_fixture_ingest():
    db = SessionLocal()
    try:
        result = trigger_dataset_sync("faers", db=db, limit=20, force_fixture=True)
        assert result["ok"] is True
        assert result["drug_exposures"] >= 1
        assert result["condition_occurrences"] >= 1
    finally:
        db.close()


def test_sider_baseline_ingest():
    db = SessionLocal()
    try:
        result = trigger_dataset_sync("sider", db=db, force_fixture=True)
        assert result["ok"] is True
        assert result["baselines_inserted"] + result["skipped"] >= 5
        rows = db.query(DrugConditionBaseline).filter(
            DrugConditionBaseline.is_expected_baseline.is_(True)
        ).count()
        assert rows >= 5
    finally:
        db.close()


def test_athena_vocab_sync():
    result = trigger_dataset_sync("athena_vocab")
    assert result["ok"] is True
    assert result.get("drug_concepts", 0) >= 5


def test_mcn_benchmark_f1_gate():
    out = run_mcn_benchmark()
    assert out["ok"] is True
    assert out["n_cases"] >= 15
    assert out["strict"]["f1"] > 0 or out["relaxed"]["f1"] > 0
    # Product gate: F1 > 0.85 on Mantra/CADEC teaching pack
    assert out["primary_f1"] > 0.85
    assert out["pass_gate"] is True


def test_etl_routes():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/etl/datasets").status_code == 200
    res = client.get("/api/etl/sync/athena_vocab")
    assert res.status_code == 200
    assert res.json().get("ok") is True
    bench = client.get("/api/etl/mcn-benchmark")
    assert bench.status_code == 200
    assert bench.json().get("pass_gate") is True
