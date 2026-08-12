"""Deep Medical Concept Normalization — Mantra GSC / CADEC-inspired gate."""
from __future__ import annotations

import pytest

from app.normalization import (
    aggregate_clinical_cohorts,
    diabetes_demo_cohort,
    engine_status,
    evaluate_clinical_f1,
    evaluate_geo_f1,
    mapping_trace,
    normalize_clinical_and_geo_entities,
    normalize_clinical_term,
    normalize_location,
)
from app.normalization.models import MentionInput
from app.normalization.sapbert_encoder import encode_span, get_encoder


def test_encoder_returns_dense_vector():
    enc = get_encoder()
    vec = encode_span("hard to stay awake")
    assert vec.ndim == 1
    assert vec.shape[0] == enc.dim
    assert float(abs(vec).sum()) > 0


def test_umls_link_somnolence_slang():
    link = normalize_clinical_term("hard to stay awake")
    assert link.matched
    assert link.meddra_pt == "Somnolence"
    assert link.cui == "CUI-SUR-SOMNO"
    assert link.snomed_ct and link.snomed_ct.startswith("SNOMED_SUR:")
    assert link.embedding is not None
    assert link.embedding.vector_dim >= 64


def test_diabetes_variants_share_cui():
    a = normalize_clinical_term("diabetic")
    b = normalize_clinical_term("Type 2 diabetic mellitus")
    c = normalize_clinical_term("diabetes")
    assert a.matched and b.matched and c.matched
    assert a.cui == b.cui == c.cui == "CUI-SUR-0011869"
    assert a.meddra_pt == "Diabetes mellitus"


def test_cohort_aggregation_sums_patient_counts():
    result = diabetes_demo_cohort()
    assert len(result.cohorts) == 1
    cohort = result.cohorts[0]
    assert cohort.cui == "CUI-SUR-0011869"
    assert cohort.patient_count == 10
    assert set(cohort.variants) >= {"diabetic", "Type 2 diabetic mellitus", "diabetes"}
    assert result.total_patients == 10


def test_aggregate_accepts_tuple_payloads():
    result = aggregate_clinical_cohorts(
        [
            MentionInput(verbatim="nausea", patient_count=1),
            ("sick to my stomach", 4),
            {"verbatim": "racing heart", "patient_count": 2},
        ]
    )
    by_cui = {c.cui: c for c in result.cohorts}
    assert by_cui["CUI-SUR-0027497"].patient_count == 5
    assert by_cui["CUI-SUR-0030252"].patient_count == 2


def test_geo_madras_chennai_and_bangalore_bengaluru():
    madras = normalize_location("Madras")
    assert madras.matched
    assert madras.canonical == "Chennai"
    assert madras.lat and madras.lon
    bangalore = normalize_location("Bangalore")
    assert bangalore.matched
    assert bangalore.canonical == "Bengaluru"


def test_joint_clinical_and_geo_mcp_payload():
    payload = normalize_clinical_and_geo_entities("racing heart", "Bombay")
    assert payload.clinical.matched
    assert payload.clinical.meddra_pt == "Palpitations"
    assert payload.geography.matched
    assert payload.geography.canonical == "Mumbai"
    assert payload.audit.is_surrogate
    dumped = payload.model_dump()
    assert "cui" in dumped["clinical"]
    assert "lat" in dumped["geography"]


def test_mapping_trace_exposes_pipeline_steps():
    trace = mapping_trace("lou gehrig's disease")
    assert trace.clinical.matched
    assert trace.clinical.meddra_pt == "Amyotrophic lateral sclerosis"
    assert len(trace.pipeline_steps) >= 3
    assert trace.pipeline_steps[0]["name"] == "sapbert_encoder"


def test_mantra_cadec_clinical_f1_exceeds_gate():
    metrics = evaluate_clinical_f1()
    assert metrics.n_cases >= 15
    assert metrics.f1 > 0.85, f"clinical F1={metrics.f1} precision={metrics.precision} recall={metrics.recall}"


def test_geo_eval_f1_exceeds_gate():
    metrics = evaluate_geo_f1()
    assert metrics.n_cases >= 8
    assert metrics.f1 > 0.85, f"geo F1={metrics.f1}"


def test_engine_status_lists_pipeline():
    status = engine_status()
    assert status["version"].startswith("2026.08-mcn")
    assert status["concepts"] >= 15
    assert status["places"] >= 10
    assert len(status["pipeline"]) == 5


def test_unmatched_clinical_is_honest():
    link = normalize_clinical_term("banana bread pudding xyz")
    assert not link.matched
    assert link.cui is None
