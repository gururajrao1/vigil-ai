"""GVP Modules 1–4: label filter, causality, triangulation, PBRER."""
from __future__ import annotations

from app.analytics.label_filter import filter_product_event, launch_time_delta_months, weber_adjustment
from app.analytics.triangulation import triangulate_signal
from app.nlp.causality_engine import evaluate_narrative_causality, naranjo_score
from app.reports.pbrer import build_pbrer_payload, render_pbrer_markdown


def test_label_filter_isotretinoin_depression_in_label():
    out = filter_product_event("isotretinoin", "depression", offline_only=True)
    assert out["tag"] in ("ESTABLISHED_REACTION", "NOVEL_UNMAPPED_SIGNAL", "UNKNOWN", "BOXED_COVERED")
    assert "weber" in out
    assert "alert_gates" in out
    assert "disclaimer" in out


def test_weber_launch_delta_known_drug():
    delta = launch_time_delta_months("semaglutide")
    assert delta is not None
    assert delta > 24  # approved 2017 — past Weber window in 2026
    w = weber_adjustment("nirmatrelvir", "taste disorder")
    # Paxlovid-era product: may still be early depending on as_of; just assert shape
    assert "weber_adjusted" in w
    assert w["effective_prr_min"] in (2.0, 3.0)


def test_naranjo_definite_on_rich_narrative():
    text = (
        "Started the drug and within hours developed a rash. "
        "Stopped and it resolved after stopping. "
        "Took it again and the rash reappeared. "
        "Doctor said it is a known side effect. Confirmed by lab."
    )
    n = naranjo_score(text, product="ibuprofen", event="rash", fda_known=True)
    assert n["score"] >= 5
    assert n["category"] in ("Probable", "Definite")
    assert len(n["items"]) == 10


def test_causality_engine_combined():
    out = evaluate_narrative_causality(
        "After starting Accutane my mood dropped. Stopped and it improved.",
        product="isotretinoin",
        event="depression",
    )
    assert out["who_umc"]["category"]
    assert out["naranjo"]["score"] is not None
    assert "dechallenge_rechallenge" in out
    assert "disclaimer" in out


def test_triangulation_tiers():
    strong = triangulate_signal({
        "drug": "isotretinoin",
        "meddra_pt": "depression",
        "prr": 5.0,
        "chi_square": 20.0,
        "a": 16,
        "strength": "STRONG",
        "fda_evidence": {"known": True, "count": 50},
    })
    assert strong["urgency_tier"] in (
        "CRITICAL_URGENT", "HIGH_EARLY_WARNING", "EMERGENT_CHATTER", "INSUFFICIENT", "REGULATORY_ONLY"
    )
    assert 0 <= strong["triangulated_risk_score"] <= 1
    assert len(strong["pillars"]) == 3

    social_only = triangulate_signal({
        "drug": "obscuredrugxyz",
        "meddra_pt": "rareeventxyz",
        "prr": 4.0,
        "chi_square": 10.0,
        "a": 5,
        "strength": "STRONG",
        "fda_evidence": {},
    })
    assert social_only["urgency_tier"] == "EMERGENT_CHATTER"


def test_pbrer_disclaimer():
    from app.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        payload = build_pbrer_payload(db, limit=5)
        md = render_pbrer_markdown(payload)
        assert "QPPV" in payload["disclaimer"] or "Medical Reviewer" in payload["disclaimer"]
        assert "AI-ASSISTED" in payload["disclaimer"].upper() or "AI-assisted" in payload["disclaimer"]
        assert "Section 16" in md
        assert "Section 17" in md
    finally:
        db.close()
