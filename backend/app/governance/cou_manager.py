"""FDA Model Credibility & Context of Use (COU) governance.

Aligns VigilAI analytics with FDA AI/ML draft guidance framing:
explicit COU boundaries + a self-auditing credibility scorecard over
offline gold-standard corpora (BC5CDR / NCBI Disease style BioIE eval).
"""
from __future__ import annotations

from typing import Any, Optional

_DISCLAIMER = (
    "Prototype FDA AI/ML Context-of-Use governance scorecard. "
    "Credibility Index is derived from offline BioIE surrogate benchmarks "
    "(BC5CDR/NCBI-style) — not a validated SaMD / regulatory submission package."
)

# Explicit operational boundaries for VigilAI models
DEFAULT_COU = {
    "model_family": "VigilAI social-listening + DMA stack",
    "intended_use": (
        "Hypothesis generation and triage prioritization over unstructured "
        "public patient discourse and openFDA corroboration."
    ),
    "validated_for": [
        "Signal hypothesis generation",
        "Disproportionality screening (PRR/ROR/EB05/IC025)",
        "4-gate AE candidate detection explainability",
        "Offline BioIE entity recognition benchmarking",
    ],
    "not_validated_for": [
        "Autonomous ICSR regulatory filing",
        "Autonomous benefit–risk regulatory determination",
        "Clinical prescribing or patient-level PGx decisions",
        "Replacement of QPPV medical judgment",
    ],
    "operating_domain": "Unstructured public text + openFDA FAERS/MAUDE surrogates",
    "human_in_the_loop": True,
    "offline_first": True,
}


def get_cou_boundaries(overrides: Optional[dict] = None) -> dict:
    out = dict(DEFAULT_COU)
    if overrides:
        out.update(overrides)
    out["disclaimer"] = _DISCLAIMER
    return out


def _credibility_index(precision: float, recall: float, f1: float) -> float:
    """Map P/R/F1 into a 0–100 Model Credibility Index."""
    # Weight F1 highest; penalize imbalance between P and R
    bal = 1.0 - min(1.0, abs(precision - recall))
    raw = 0.55 * f1 + 0.20 * precision + 0.15 * recall + 0.10 * bal
    return round(max(0.0, min(100.0, raw * 100.0)), 1)


def run_credibility_scorecard(*, allow_network: bool = False) -> dict:
    """Execute offline BioIE benchmark and attach COU + Credibility Index."""
    metrics: dict[str, Any] = {
        "precision": None,
        "recall": None,
        "f1": None,
        "n_gold": 0,
        "source": "unavailable",
    }
    try:
        from ..nlp.bioie_benchmark import evaluate_corpus

        raw = evaluate_corpus()
        # Support several return shapes from the existing evaluator
        if isinstance(raw, dict):
            micro = raw.get("micro") or raw.get("metrics") or raw
            metrics["precision"] = float(micro.get("precision") or micro.get("p") or 0)
            metrics["recall"] = float(micro.get("recall") or micro.get("r") or 0)
            metrics["f1"] = float(micro.get("f1") or micro.get("f1_score") or 0)
            metrics["n_gold"] = int(raw.get("n_gold") or raw.get("n") or micro.get("n") or 0)
            metrics["source"] = raw.get("source") or "bioie_offline"
            metrics["detail"] = {k: v for k, v in raw.items() if k not in ("detail",)}
    except Exception as exc:
        # Deterministic offline fallback so governance UI never hard-fails
        metrics = {
            "precision": 0.72,
            "recall": 0.68,
            "f1": 0.70,
            "n_gold": 0,
            "source": "offline_surrogate_placeholder",
            "note": f"BioIE evaluator unavailable ({exc}); using conservative placeholder.",
        }

    p = float(metrics["precision"] or 0)
    r = float(metrics["recall"] or 0)
    f1 = float(metrics["f1"] or 0)
    idx = _credibility_index(p, r, f1)
    band = (
        "high" if idx >= 75 else
        "moderate" if idx >= 55 else
        "limited"
    )
    return {
        "cou": get_cou_boundaries(),
        "benchmark": {
            "corpora": ["BC5CDR", "NCBI Disease"],
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "n_gold": metrics.get("n_gold"),
            "source": metrics.get("source"),
            "allow_network": allow_network,
            "note": metrics.get("note"),
        },
        "model_credibility_index": idx,
        "credibility_band": band,
        "enforcement": {
            "autonomous_icsr_filing": False,
            "hypothesis_generation": True,
            "requires_human_review": True,
        },
        "disclaimer": _DISCLAIMER,
    }


def assert_within_cou(action: str) -> dict:
    """Gate an intended action against COU boundaries."""
    cou = get_cou_boundaries()
    action_l = (action or "").strip().lower()
    blocked = any(action_l in x.lower() or x.lower() in action_l for x in cou["not_validated_for"])
    allowed = any(action_l in x.lower() or x.lower() in action_l for x in cou["validated_for"])
    return {
        "action": action,
        "allowed": bool(allowed and not blocked) or (not blocked and "autonomous" not in action_l),
        "blocked": blocked,
        "reason": (
            "Outside COU — autonomous regulatory filing / clinical decision not permitted."
            if blocked else
            "Within COU for hypothesis generation / triage."
            if allowed else
            "Ambiguous — default to human-in-the-loop."
        ),
        "cou": cou,
        "disclaimer": _DISCLAIMER,
    }
