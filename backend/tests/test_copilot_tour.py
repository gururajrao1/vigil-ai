"""Tests for plain-English Signal Detail feature tour + Q&A."""
from app.analytics.copilot_tour import (
    answer_question,
    attach_feature_tour,
    build_feature_tour,
)
from app.analytics.copilot import generate_assessment


def _sample_sig():
    return {
        "drug": "isotretinoin",
        "symptom": "depression",
        "meddra": {"pt": "Depression", "soc": "Psychiatric disorders"},
        "post_count": 12,
        "prr": 3.2,
        "ror": 3.5,
        "chi_square": 9.1,
        "eb05": 1.8,
        "ic025": 0.4,
        "strength": "STRONG",
        "sdr_flag": True,
        "spike_flag": True,
        "spike_z": 2.4,
        "trend_score": 0.12,
        "who_umc": "Possible",
        "who_umc_score": 0.45,
        "maxsprt_llr": 3.1,
        "maxsprt_crossed": True,
        "maxsprt": {"llr": 3.1, "crossed": True, "critical_value": 2.5},
        "hr": 1.8,
        "hr_ci": [1.1, 2.9],
        "hr_elevated": True,
        "e_value": 2.1,
        "calibrated_p": 0.02,
        "calibrated_signal": True,
        "label_filter": {
            "tag": "NOVEL_UNMAPPED_SIGNAL",
            "is_in_label": False,
            "novelty_tier": "novel",
            "alert_gates": {"prr_min": 2.0, "weber_adjusted": False},
            "weber": {"weber_adjusted": False},
        },
        "causality_assessment": {
            "who_umc": {"category": "Possible", "score": 0.45},
            "naranjo": {"category": "Possible", "score": 4},
        },
        "triangulation": {
            "badge": "HIGH EARLY WARNING",
            "urgency_tier": "HIGH_EARLY_WARNING",
            "n_pillars_passed": 2,
            "triangulated_risk_score": 0.62,
            "pillars": [
                {"name": "social", "passed": True, "score": 0.7},
                {"name": "regulatory", "passed": True, "score": 0.5},
                {"name": "rwd", "passed": False, "score": 0.1},
            ],
        },
        "completeness": 0.55,
        "well_documented": True,
        "completeness_detail": {"mean_completeness": 0.55, "grade": "C", "well_documented": True, "n_posts": 12},
        "trust_score": 0.8,
        "trust_label": "high",
        "lifecycle_status": "under_evaluation",
        "priority_score": 0.72,
        "thread_score": {
            "rag": "Amber",
            "confidence": 0.6,
            "corroborating": 5,
            "contradicting": 1,
            "ae_flagged": 8,
            "n_posts": 12,
        },
        "fda_evidence": {"available": True, "source": "faers", "report_count": 40},
        "drug_atc": "D10BA01",
    }


def test_tour_covers_core_panels():
    tour = build_feature_tour(_sample_sig())
    ids = {s["id"] for s in tour}
    for need in (
        "remine", "disproportionality", "bayesian", "trend", "maxsprt", "cox",
        "calibration", "label_filter", "causality", "triangulation", "completeness",
        "trust", "lifecycle", "thread_score", "faers_maude", "ontology", "four_gate",
        "disclaimer",
    ):
        assert need in ids, f"missing {need}"
    assert all(s.get("what_it_is") and s.get("so_what") for s in tour)


def test_ask_prr_and_four_gate():
    sig = _sample_sig()
    r = answer_question(sig, "What does PRR mean?")
    assert r["matched_feature"] == "disproportionality"
    assert "PRR" in r["answer"] or "smoke" in r["answer"].lower()

    r2 = answer_question(sig, "Explain the 4-gate AE detector")
    assert r2["matched_feature"] == "four_gate"


def test_generate_assessment_includes_tour():
    out = generate_assessment(_sample_sig(), allow_llm=False)
    assert out["source"] == "deterministic"
    assert len(out["feature_tour"]) >= 10
    assert "plain_english_tour" in out
    assert "audience_note" in out


def test_bottom_line_loud_but_fragile():
    """Screenshot-like case: huge PRR + SDR + EB05 ok, but n=4, IC025<0, cal fail, poor docs."""
    from app.analytics.copilot_verdicts import build_bottom_line, apply_verdicts
    from app.analytics.copilot_tour import build_feature_tour, answer_question

    sig = {
        "drug": "demo-drug",
        "symptom": "demo-event",
        "meddra": {"pt": "demo-event"},
        "post_count": 4,
        "prr": 2185.2,
        "ror": 21843.0,
        "chi_square": 930.89,
        "prr_ci": [134.67, 35458.21],
        "eb05": 6.96,
        "ic025": -1.03,
        "strength": "STRONG",
        "sdr_flag": True,
        "calibrated_p": 0.1083,
        "calibrated_signal": False,
        "e_value": 4369.9,
        "completeness": 0.46,
        "well_documented": False,
        "completeness_detail": {"mean_completeness": 0.46, "well_documented": False},
        "who_umc": "Possible",
        "trust_label": "high",
    }
    bottom = build_bottom_line(sig)
    assert bottom["tone"] == "mixed"
    assert "fragile" in bottom["label"].lower() or "mixed" in bottom["label"].lower()
    assert any("noise" in c.lower() or "calibrat" in c.lower() for c in bottom["coolers"])

    tour, bl = apply_verdicts(build_feature_tour(sig), sig)
    by_id = {s["id"]: s for s in tour}
    assert by_id["disproportionality"]["verdict"] == "mixed"
    assert "investigate" in by_id["disproportionality"]["takeaway"].lower() or "fragile" in by_id["disproportionality"]["takeaway"].lower() or "LOOKS BAD" in by_id["disproportionality"]["takeaway"]
    assert by_id["bayesian"]["verdict"] == "mixed"
    assert by_id["calibration"]["verdict"] == "reassuring"
    assert by_id["completeness"]["verdict"] == "caution"

    r = answer_question(sig, "Is this bad?")
    assert r["matched_feature"] == "bottom_line"
    assert "Mixed" in r["answer"] or "fragile" in r["answer"].lower()


def test_attach_includes_bottom_line():
    out = attach_feature_tour({"tour_only": True}, _sample_sig())
    assert out["bottom_line"]["headline"]
    assert any(s.get("takeaway") for s in out["feature_tour"])

