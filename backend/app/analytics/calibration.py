"""Empirical calibration (negative controls) + E-values.

Spontaneous-report disproportionality over-flags because the "null" is not truly
"no association" — systematic error (confounding by indication, notoriety/stimulated
reporting, masking) shifts and widens it. Following Schuemie et al. (OHDSI), we estimate
the **empirical null** from a panel of **negative controls** (drug-event pairs with no
known causal link) via a DerSimonian-Laird-style moment estimator, then calibrate every
signal against the *observed* noise floor rather than the theoretical null.

We also compute the **E-value** (VanderWeele & Ding): the minimum association strength,
on the risk-ratio scale, an unmeasured confounder would need with both drug and event to
fully explain the signal away. Larger E-value = more robust to residual confounding.

Deterministic + offline. Uses the signal's IC (BCPNN, log2 scale) as the test statistic
(with an approximate SE) and PRR as the risk-ratio proxy for the E-value.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

_LN2_SQ = math.log(2.0) ** 2
_Z = 1.96

# --------------------------------------------------------------------------- #
# Negative controls — (drug, normalized-symptom) pairs with no established causal
# link, matched against the corpus's normalized symptom names so they surface as
# in-data controls defining the empirical noise floor. Curated / illustrative.
# --------------------------------------------------------------------------- #
NEGATIVE_CONTROLS: set[tuple[str, str]] = {
    ("metformin", "headache"), ("metformin", "dizziness"), ("metformin", "back pain"),
    ("atorvastatin", "nausea"), ("atorvastatin", "dizziness"),
    ("paracetamol", "dizziness"), ("paracetamol", "back pain"),
    ("acetaminophen", "dizziness"),
    ("ibuprofen", "insomnia"), ("ibuprofen", "dizziness"),
    ("semaglutide", "headache"), ("semaglutide", "dizziness"),
    ("loxoprofen", "fatigue"), ("loxoprofen", "insomnia"),
    ("sertraline", "back pain"), ("gabapentin", "nausea"),
    ("amoxicillin", "fatigue"), ("amoxicillin clavulanate", "fatigue"),
    ("diclofenac", "fatigue"), ("pregabalin", "nausea"),
    ("rivaroxaban", "nausea"), ("isotretinoin", "nausea"),
    ("levothyroxine", "back pain"), ("omeprazole", "back pain"),
}


def _norm(x: str | None) -> str:
    return (x or "").strip().lower()


def is_negative_control(drug: str | None, symptom: str | None) -> bool:
    return (_norm(drug), _norm(symptom)) in NEGATIVE_CONTROLS


def _phi(x: float) -> float:
    """Standard normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ic_se(a: float, expected: float) -> float:
    """Approximate SE of the IC (log2 scale), matching the disproportionality module."""
    return math.sqrt((1.0 / _LN2_SQ) * (1.0 / (a + 0.5) + 1.0 / (expected + 0.5)))


def fit_null(observations: List[Tuple[float, float]]) -> dict:
    """Empirical null from negative-control (estimate, SE) pairs.

    DerSimonian-Laird-style moment estimator: mu = mean of the estimates; sigma^2 =
    residual (between-control) variance beyond sampling error. Low-N/degenerate cases
    fall back to the standard null (mu=0, sigma=0) with ``calibrated=False`` so
    calibration is a transparent no-op rather than a guess.
    """
    n = len(observations)
    if n < 3:
        return {"calibrated": False, "mu": 0.0, "sigma": 0.0, "n": n}
    ests = [e for e, _ in observations]
    ses = [s for _, s in observations]
    mu = sum(ests) / n
    total_var = sum((e - mu) ** 2 for e in ests) / (n - 1)
    mean_sampling_var = sum(s * s for s in ses) / n
    sigma = math.sqrt(max(0.0, total_var - mean_sampling_var))
    return {"calibrated": True, "mu": round(mu, 4), "sigma": round(sigma, 4), "n": n}


def e_value(rr: float | None, rr_lower: float | None) -> Dict[str, float]:
    """E-value for the point estimate and the CI lower bound (RR proxy = PRR)."""
    def ev(x: float | None) -> float:
        if x is None or x <= 1.0:
            return 1.0
        return round(x + math.sqrt(x * (x - 1.0)), 2)
    return {"e_value": ev(rr), "e_value_ci": ev(rr_lower)}


def calibrate_signals(signals: List[dict]) -> Tuple[dict, Dict[Tuple[str, str], dict]]:
    """Fit the empirical null from negative-control signals, then calibrate every signal.

    Returns ``(null, calib_map)`` where ``calib_map[(drug, symptom)]`` carries the
    calibrated p-value + calibrated IC CI, the fitted-null summary, and the E-values.
    """
    # Build the negative-control observation panel on the IC scale.
    obs: List[Tuple[float, float]] = []
    for s in signals:
        if s.get("ic") is None:
            continue
        if is_negative_control(s.get("drug"), s.get("symptom")):
            obs.append((s["ic"], _ic_se(s.get("post_count") or 0.0, s.get("expected") or 0.0)))

    null = fit_null(obs)
    mu, sigma, n = null["mu"], null["sigma"], null["n"]

    calib_map: Dict[Tuple[str, str], dict] = {}
    for s in signals:
        ic = s.get("ic")
        ev = e_value(s.get("prr"), s.get("prr_ci_low"))
        if ic is None:
            calib_map[(s["drug"], s["symptom"])] = {
                "calibrated_p": None, "calibrated": null["calibrated"],
                "calibrated_ci": None, "null_mu": mu, "null_sigma": sigma,
                "n_controls": n, **ev,
            }
            continue
        se = _ic_se(s.get("post_count") or 0.0, s.get("expected") or 0.0)
        denom = math.sqrt(se * se + sigma * sigma) or 1.0
        z = (ic - mu) / denom
        calibrated_p = round(1.0 - _phi(z), 4)          # one-sided (elevated)
        centered = ic - mu
        half = _Z * denom
        calibrated_ci = [round(centered - half, 3), round(centered + half, 3)]
        calib_map[(s["drug"], s["symptom"])] = {
            "calibrated_p": calibrated_p,
            "calibrated": null["calibrated"],
            "calibrated_ci": calibrated_ci,
            "null_mu": mu, "null_sigma": sigma, "n_controls": n,
            **ev,
        }
    return null, calib_map


def summary(signals: List[dict]) -> dict:
    """Fitted-null summary + negative-control panel (for the /api/calibration view)."""
    null, _ = calibrate_signals(signals)
    return {
        "null_mu": null["mu"],
        "null_sigma": null["sigma"],
        "n_controls": null["n"],
        "calibrated": null["calibrated"],
        "negative_controls": sorted(f"{d} -> {e}" for d, e in NEGATIVE_CONTROLS),
        "n_controls_defined": len(NEGATIVE_CONTROLS),
        "note": "Empirical-null calibration (Schuemie/OHDSI) + E-values (VanderWeele & "
                "Ding): calibrated p-values are measured against the observed noise floor "
                "of negative controls, not the theoretical null.",
    }


def calibration_summary_from_rows(rows) -> dict:
    """Build the /api/calibration summary from stored Signal ORM rows."""
    signals = [
        {"drug": r.drug, "symptom": r.symptom, "ic": r.ic,
         "post_count": r.post_count, "expected": r.expected,
         "prr": r.prr, "prr_ci_low": r.prr_ci_low}
        for r in rows
    ]
    out = summary(signals)
    out["n_calibrated_signals"] = sum(1 for r in rows if getattr(r, "calibrated_signal", False))
    return out
