"""Validation suite for the 4-gate AE engine + concept-level drug dedupe."""
from __future__ import annotations

from app.nlp.ae_detector import (
    detect_ae,
    evaluate_ae_stream,
    evaluate_ae_text,
    unique_drug_concepts,
)


BRAND_MAP = {
    "lyrica": "pregabalin",
    "accutane": "isotretinoin",
    "ozempic": "semaglutide",
}


def test_brand_generic_collapse_to_one_concept():
    """Lyrica + Pregabalin must count as ONE unique drug concept (Gate 1)."""
    drugs = [
        {"text": "Lyrica", "normalized": "pregabalin", "generic": "pregabalin", "start": 0},
        {"text": "Pregabalin", "normalized": "pregabalin", "generic": "pregabalin", "start": 20},
    ]
    concepts = unique_drug_concepts(drugs, brand_map=BRAND_MAP)
    assert len(concepts) == 1
    assert concepts[0]["concept"] == "pregabalin"
    assert set(concepts[0]["surfaces"]) == {"Lyrica", "Pregabalin"}

    result = detect_ae(
        {"drugs": drugs, "symptoms": [{"text": "dizziness", "normalized": "dizziness", "start": 40}]},
        {"label": "NEGATIVE", "score": -0.6},
        {"dizziness": False},
        brand_map=BRAND_MAP,
    )
    assert result["explainability"]["gate_1"]["status"] is True
    assert result["explainability"]["gate_1"]["count"] == 1
    assert result["explainability"]["gate_1"]["items"] == ["pregabalin"]
    assert result["unique_drug_count"] == 1
    assert result["ae_flag"] is True


def test_two_distinct_drugs_remain_two():
    drugs = [
        {"text": "Ozempic", "normalized": "semaglutide", "generic": "semaglutide"},
        {"text": "metformin", "normalized": "metformin", "generic": "metformin"},
    ]
    concepts = unique_drug_concepts(drugs, brand_map=BRAND_MAP)
    assert len(concepts) == 2
    assert {c["concept"] for c in concepts} == {"semaglutide", "metformin"}


def test_gate2_fail_no_symptom():
    result = detect_ae(
        {"drugs": [{"text": "ibuprofen", "normalized": "ibuprofen", "generic": "ibuprofen"}],
         "symptoms": []},
        {"label": "NEGATIVE", "score": -0.5},
        {},
    )
    assert result["ae_flag"] is False
    assert result["explainability"]["gate_2"]["status"] is False
    assert result["explainability"]["gate_2"]["count"] == 0
    assert "failed_gate_2" in result["reason"]


def test_gate3_fail_positive_sentiment():
    result = detect_ae(
        {
            "drugs": [{"text": "sertraline", "normalized": "sertraline", "generic": "sertraline"}],
            "symptoms": [{"text": "nausea", "normalized": "nausea"}],
        },
        {"label": "POSITIVE", "score": 0.7},
        {"nausea": False},
    )
    assert result["ae_flag"] is False
    assert result["explainability"]["gate_3"]["status"] is False


def test_gate4_fail_all_symptoms_negated():
    result = detect_ae(
        {
            "drugs": [{"text": "Accutane", "normalized": "isotretinoin", "generic": "isotretinoin"}],
            "symptoms": [{"text": "depression", "normalized": "depression"}],
        },
        {"label": "NEGATIVE", "score": -0.4},
        {"depression": True},
        brand_map=BRAND_MAP,
    )
    assert result["ae_flag"] is False
    assert result["explainability"]["gate_4"]["status"] is False
    assert result["explainability"]["gate_4"]["count"] == 0
    assert "depression" in result["explainability"]["gate_4"]["negated_items"]


def test_explainability_schema_keys():
    result = detect_ae(
        {
            "drugs": [{"text": "ciprofloxacin", "normalized": "ciprofloxacin", "generic": "ciprofloxacin"}],
            "symptoms": [{"text": "tendon pain", "normalized": "tendon pain"}],
        },
        {"label": "NEGATIVE", "score": -0.55},
        {"tendon pain": False},
    )
    exp = result["explainability"]
    for key in ("gate_1", "gate_2", "gate_3", "gate_4"):
        assert key in exp
        assert "status" in exp[key] and isinstance(exp[key]["status"], bool)
        assert "count" in exp[key] and isinstance(exp[key]["count"], int)
        assert "items" in exp[key] and isinstance(exp[key]["items"], list)
    # legacy list still present for GateTrace UI
    assert isinstance(result["gate_trace"], list) and len(result["gate_trace"]) == 4
    assert all("passed" in g and "status" in g for g in result["gate_trace"])


def test_evaluate_ae_text_end_to_end_offline():
    """Full path: raw patient text → entities → 4 gates (no hard-coded drug vars)."""
    text = (
        "Started Lyrica last week and now I have terrible dizziness and nausea. "
        "Also taking pregabalin as prescribed — this side effect is awful."
    )
    result = evaluate_ae_text(text, brand_map=BRAND_MAP, use_transformer=False)
    assert result["explainability"]["gate_1"]["count"] == 1  # Lyrica+pregabalin collapsed
    assert result["explainability"]["gate_1"]["items"] == ["pregabalin"]
    assert result["explainability"]["gate_2"]["count"] >= 1
    # Gate 3/4 depend on VADER + lexicon; assert schema always present
    assert "gate_3" in result["explainability"]
    assert "gate_4" in result["explainability"]


def test_evaluate_ae_stream_dynamic_dataset():
    """Simulate Kaggle ADE / openFDA-style records — no single-drug hardcoding."""
    rows = [
        {"id": "ade-1", "text": "Patient on Accutane developed severe depression and dry skin.",
         "drug": "Accutane", "ade": "depression"},
        {"id": "ade-2", "text": "No rash while taking ibuprofen for headache — feeling fine.",
         "drug": "ibuprofen"},
        {"id": "faers-9", "narrative": "Ozempic caused persistent vomiting and abdominal pain.",
         "source": "openFDA"},
    ]
    # Map narrative → text_field dynamically for mixed schemas
    normalized = []
    for r in rows:
        normalized.append({
            **r,
            "text": r.get("text") or r.get("narrative") or "",
        })
    results = evaluate_ae_stream(normalized, brand_map=BRAND_MAP, use_transformer=False)
    assert len(results) == 3
    # First: Accutane → isotretinoin unique concept
    g1 = results[0]["explainability"]["gate_1"]
    assert g1["status"] is True
    assert g1["count"] >= 1
    assert "isotretinoin" in g1["items"] or "accutane" in g1["items"]
    # Every row exposes the UI schema
    for r in results:
        assert set(r["explainability"].keys()) >= {"gate_1", "gate_2", "gate_3", "gate_4"}


def test_empty_text_fails_cleanly():
    result = evaluate_ae_text("", brand_map=BRAND_MAP)
    assert result["ae_flag"] is False
    assert result["explainability"]["gate_1"]["count"] == 0


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    tests = [
        test_brand_generic_collapse_to_one_concept,
        test_two_distinct_drugs_remain_two,
        test_gate2_fail_no_symptom,
        test_gate3_fail_positive_sentiment,
        test_gate4_fail_all_symptoms_negated,
        test_explainability_schema_keys,
        test_evaluate_ae_text_end_to_end_offline,
        test_evaluate_ae_stream_dynamic_dataset,
        test_empty_text_fails_cleanly,
    ]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print("=== AE DETECTOR TESTS OK ===")
