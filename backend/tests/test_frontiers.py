"""Tests for next-gen PV frontiers (inspection, COU, PGx, ATMP, lot, PrOACT)."""
from datetime import datetime, timedelta

from app.analytics.benefit_risk import evaluate_benefit_risk_ratio
from app.analytics.longitudinal_biologics import (
    assess_signal_longitudinal,
    extract_onset_days,
    parse_immunogenicity_events,
)
from app.analytics.lot_clustering import assess_lot_clustering, extract_lot_cues
from app.analytics.pgx_engine import get_pgx_gene_associations, offline_match
from app.governance.cou_manager import assert_within_cou, get_cou_boundaries, run_credibility_scorecard
from app.reports.inspection_audit import (
    build_sj_entry,
    inspection_risk_for_signal,
    require_justification,
    review_lead_time_days,
)


class _Sig:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.drug = kw.get("drug", "carbamazepine")
        self.symptom = kw.get("symptom", "rash")
        self.meddra_pt = kw.get("meddra_pt", "Stevens-Johnson syndrome")
        self.strength = kw.get("strength", "STRONG")
        self.sdr_flag = kw.get("sdr_flag", True)
        self.severity = kw.get("severity", "High")
        self.lifecycle_status = kw.get("lifecycle_status", "new")
        self.lifecycle_notes = kw.get("lifecycle_notes", "")
        self.lifecycle_updated_at = kw.get("lifecycle_updated_at")
        self.detected_at = kw.get("detected_at", datetime.utcnow() - timedelta(days=20))
        self.first_seen = self.detected_at
        self.maxsprt_crossed = False
        self.post_count = kw.get("post_count", 5)


def test_inspection_sla_overdue():
    sig = _Sig()
    lead = review_lead_time_days(sig)
    assert lead is not None and lead >= 19
    risk = inspection_risk_for_signal(sig)
    assert risk["badge"] == "INSPECTION_RISK_WARNING"
    assert risk["overdue"] is True


def test_justification_required_on_close():
    assert require_justification("closed", "short") is not None
    assert require_justification("closed", "x" * 45) is None
    assert require_justification("under_evaluation", "") is None


def test_sjl_hash_chain():
    e1 = build_sj_entry(
        signal_id=1, actor="qppv", action="close",
        from_status="assessed", to_status="closed",
        rationale="Insufficient corroboration after FAERS review and medical evaluation.",
    )
    assert len(e1["action_hash"]) == 64
    e2 = build_sj_entry(
        signal_id=1, actor="qppv", action="note",
        from_status="closed", to_status="closed",
        rationale="Follow-up note", prev_hash=e1["action_hash"],
    )
    assert e2["prev_hash"] == e1["action_hash"]
    assert e2["action_hash"] != e1["action_hash"]


def test_cou_boundaries_and_scorecard():
    cou = get_cou_boundaries()
    assert "Hypothesis generation" in cou["validated_for"][0] or "hypothesis" in cou["validated_for"][0].lower()
    blocked = assert_within_cou("Autonomous ICSR regulatory filing")
    assert blocked["blocked"] is True
    card = run_credibility_scorecard(allow_network=False)
    assert 0 <= card["model_credibility_index"] <= 100
    assert "precision" in card["benchmark"]


def test_pgx_carbamazepine_sjs():
    hit = offline_match("carbamazepine", "stevens-johnson syndrome")
    assert hit and hit["is_pgx_actionable"]
    assert "HLA-B" in hit["gene"]
    assoc = get_pgx_gene_associations("carbamazepine", event="rash", offline_only=True)
    assert assoc["is_pgx_actionable"]


def test_crs_icans_and_onset():
    text = "Patient developed cytokine release syndrome on day 5 after CAR-T infusion; ICANS followed."
    hits = parse_immunogenicity_events(text, product="tisagenlecleucel")
    ids = {h["event_id"] for h in hits}
    assert "crs" in ids and "icans" in ids
    assert extract_onset_days(text) == 5.0
    out = assess_signal_longitudinal(
        _Sig(drug="tisagenlecleucel", symptom="cytokine release syndrome"),
        supporting_texts=[text],
        dated_counts=[(datetime.utcnow() - timedelta(days=400), 2)],
    )
    assert out["is_advanced_therapy"] is True


def test_lot_clustering_manufacturing_flag():
    texts = [
        "Side effect after lot LOT-ABC123 — nausea",
        "Same lot LOT-ABC123 caused vomiting",
        "LOT-ABC123 again — rash",
        "LOT-ABC123 packaging bottle issue",
        "Different lot LOT-ZZZ999 mild",
    ]
    cues = extract_lot_cues(texts[0])
    assert "LOT-ABC123" in cues["lots"]
    out = assess_lot_clustering(texts, product="demo", spike=True, threshold=0.80)
    assert out["lot_clustering_coefficient"] >= 0.8
    assert out["flag"] == "MANUFACTURING_LOT_DEFECT"


def test_proact_balance_ratio():
    out = evaluate_benefit_risk_ratio(
        "sertraline", "nausea", post_count=10, strength="MODERATE", offline_only=True,
    )
    assert out["balance_ratio"] > 0
    assert "proact_dimensions" in out
    assert out["efficacy"]["response_rate_pct"] > 0
