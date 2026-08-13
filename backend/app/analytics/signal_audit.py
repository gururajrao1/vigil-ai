"""Clinical parameter transparency — signal severity / DMA audit payload.

Builds the exact PRR, ROR, IC025, and EBGM results against corporate thresholds
for the severity-audit popover. Explicitly documents data-stream limitations
(patient-voice sentiment + vernacular extraction; unverified comorbidities).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Signal

# Corporate / regulator-style thresholds (Evans / MHRA / UMC / FDA MGPS)
THRESHOLDS = {
    "prr": {
        "strong": 2.0,
        "moderate": 1.5,
        "ci_lower_sdr": 1.0,
        "chi2_sdr": 4.0,
        "n_sdr": 3,
    },
    "ror": {
        "elevated": 2.0,
        "ci_lower_sdr": 1.0,
    },
    "ic025": {
        "sdr": 0.0,  # IC025 > 0
    },
    "ebgm": {
        "eb05_sdr": 2.0,  # EB05 ≥ 2
    },
    "severity": {
        "tiers": ["Critical", "High", "Medium", "Low"],
        "critical_requires": "IME/critical-event lexicon × WHO-UMC Certain/Probable",
    },
}

DATA_LIMITATIONS = {
    "title": "Data stream boundaries",
    "summary": (
        "This ranking includes patient-voice sentiment weights and vernacular "
        "extraction checks over unstructured consumer text. Individual clinical "
        "medical comorbidities are currently unverified due to the privacy "
        "limitations of social-listening channels."
    ),
    "includes": [
        "Patient-voice sentiment polarity (4-gate AE detector gate 3)",
        "Vernacular / layman phrase mapping to MedDRA-style PTs",
        "Disproportionality on co-occurrence counts (not confirmed diagnoses)",
        "WHO-UMC causality cues from free text (temporal / dechallenge / rechallenge)",
    ],
    "excludes": [
        "Verified clinician-confirmed comorbidities",
        "Chart-reviewed exposure windows and concomitant medications",
        "Licensed MedDRA dictionary (open surrogate coding only)",
        "Validated E2B regulatory submission packages",
    ],
    "disclaimer": (
        " openFDA FAERS/MAUDE are US-only "
        "reference overlays when available."
    ),
}


def _pass_fail(value: Optional[float], op: str, threshold: float) -> dict:
    if value is None:
        return {"value": None, "threshold": threshold, "op": op, "met": False}
    if op == ">":
        met = value > threshold
    elif op == ">=":
        met = value >= threshold
    elif op == "<":
        met = value < threshold
    else:
        met = value == threshold
    return {"value": value, "threshold": threshold, "op": op, "met": bool(met)}


def _severity_rationale(sig: Signal) -> dict:
    factors = []
    try:
        factors = json.loads(sig.who_umc_factors_json or "[]")
    except Exception:
        factors = []
    return {
        "tier": sig.severity,
        "who_umc": sig.who_umc,
        "who_umc_score": sig.who_umc_score,
        "who_umc_factors": factors,
        "event": sig.meddra_pt or sig.symptom,
        "method": (
            "Severity = critical-event lexicon × WHO-UMC causality category. "
            "Critical requires an IME-class event with Certain/Probable causality; "
            "High is the same event with weaker causality; Medium/Low follow "
            "non-critical events stratified by causality."
        ),
    }


def build_signal_audit(db: Session, signal_id: int) -> Optional[dict[str, Any]]:
    sig = db.get(Signal, signal_id)
    if not sig:
        return None

    prr_t = THRESHOLDS["prr"]
    ror_t = THRESHOLDS["ror"]
    ic_t = THRESHOLDS["ic025"]
    eb_t = THRESHOLDS["ebgm"]

    prr_strong = _pass_fail(sig.prr, ">=", prr_t["strong"])
    prr_ci_sdr = _pass_fail(sig.prr_ci_low, ">=", prr_t["ci_lower_sdr"])
    chi2_sdr = _pass_fail(sig.chi_square, ">=", prr_t["chi2_sdr"])
    n_sdr = _pass_fail(float(sig.post_count or 0), ">=", float(prr_t["n_sdr"]))
    ror_elev = _pass_fail(sig.ror, ">=", ror_t["elevated"])
    ic025_sdr = _pass_fail(sig.ic025, ">", ic_t["sdr"])
    eb05_sdr = _pass_fail(sig.eb05, ">=", eb_t["eb05_sdr"])

    sdr_reasons = []
    if ic025_sdr["met"]:
        sdr_reasons.append("IC025 > 0 (BCPNN / UMC)")
    if eb05_sdr["met"]:
        sdr_reasons.append("EB05 ≥ 2 (MGPS / FDA)")
    if prr_ci_sdr["met"] and chi2_sdr["met"] and n_sdr["met"]:
        sdr_reasons.append("PRR CI lower ≥ 1 with χ² ≥ 4 and n ≥ 3 (Evans/MHRA)")

    return {
        "signal_id": sig.id,
        "product": sig.drug,
        "event": sig.meddra_pt or sig.symptom,
        "meddra": {
            "pt": sig.meddra_pt,
            "soc": sig.meddra_soc,
            "soc_code": sig.meddra_soc_code,
        },
        "severity": _severity_rationale(sig),
        "strength": sig.strength,
        "sdr_flag": bool(sig.sdr_flag),
        "sdr_reasons": sdr_reasons,
        "equations": {
            "prr": {
                "label": "Proportional Reporting Ratio",
                "formula": "PRR = (a/(a+b)) / (c/(c+d))  [Haldane-Anscombe +0.5]",
                "observed": sig.prr,
                "ci95": [sig.prr_ci_low, sig.prr_ci_high],
                "chi_square_yates": sig.chi_square,
                "post_count": sig.post_count,
                "expected": sig.expected,
                "thresholds": prr_t,
                "checks": {
                    "strong_tier": prr_strong,
                    "sdr_ci_lower": prr_ci_sdr,
                    "sdr_chi2": chi2_sdr,
                    "sdr_n": n_sdr,
                },
            },
            "ror": {
                "label": "Reporting Odds Ratio",
                "formula": "ROR = (a*d) / (b*c)  [Haldane-Anscombe +0.5]",
                "observed": sig.ror,
                "ci95": [sig.ror_ci_low, sig.ror_ci_high],
                "thresholds": ror_t,
                "checks": {
                    "elevated": ror_elev,
                },
            },
            "ic025": {
                "label": "Bayesian Information Component lower bound",
                "formula": "IC = log2((a+0.5)/(E+0.5)); IC025 ≈ IC − 1.96·√Var(IC)",
                "ic": sig.ic,
                "ic025": sig.ic025,
                "thresholds": ic_t,
                "checks": {
                    "sdr": ic025_sdr,
                },
            },
            "ebgm": {
                "label": "Empirical Bayes Geometric Mean (MGPS)",
                "formula": (
                    "λ|n,E ~ Gamma(α+n, β+E); "
                    "EBGM = exp(ψ(α+n) − ln(β+E)); EB05 = F⁻¹_Γ(0.05)/ (β+E)"
                ),
                "ebgm": sig.ebgm,
                "eb05": sig.eb05,
                "thresholds": eb_t,
                "checks": {
                    "sdr_eb05": eb05_sdr,
                },
            },
        },
        "data_limitations": DATA_LIMITATIONS,
        "thresholds_reference": THRESHOLDS,
    }
