"""Statistical disproportionality analysis for spontaneous-report-style data.

Operates on AE-flagged reports where a "report" is a (product, event) co-occurrence
within a post. Combines frequentist and Bayesian signal-detection metrics as used by
regulators (FDA/UMC) so small-N noise is controlled:

  * PRR (proportional reporting ratio) + 95% CI  -- Evans et al.
  * ROR (reporting odds ratio) + 95% CI          -- van Puijenbroek et al.
  * Yates-corrected chi-square
  * EBGM / EB05 (Gamma-Poisson shrinkage, DuMouchel-style single-component MGPS)
  * IC / IC025 (Bayesian Confidence Propagation Neural Network, Bate/Norén)

A signal of disproportionate reporting (SDR) is flagged with regulator-style
thresholds (IC025 > 0, or EB05 >= 2, or lower PRR CI >= 1 with chi2 >= 4 and n >= 3).

Haldane-Anscombe +0.5 continuity correction neutralizes zero cells / division by zero.
Pure-Python + scipy.special only; deterministic and offline.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Tuple

from scipy.special import digamma, gammaincinv  # type: ignore

CORRECTION = 0.5  # Haldane-Anscombe continuity correction for zero cells
_Z = 1.96          # 95% normal quantile


# --------------------------------------------------------------------------- #
# Frequentist components
# --------------------------------------------------------------------------- #
def _chi_square_yates(a: float, b: float, c: float, d: float) -> float:
    n = a + b + c + d
    if n == 0:
        return 0.0
    row1, row2 = a + b, c + d
    col1, col2 = a + c, b + d
    if min(row1, row2, col1, col2) == 0:
        return 0.0
    exp_a = row1 * col1 / n
    exp_b = row1 * col2 / n
    exp_c = row2 * col1 / n
    exp_d = row2 * col2 / n

    def term(o, e):
        return (abs(o - e) - 0.5) ** 2 / e if e > 0 else 0.0

    return round(term(a, exp_a) + term(b, exp_b) + term(c, exp_c) + term(d, exp_d), 3)


def _prr_ci(a: float, b: float, c: float, d: float) -> Tuple[float, float, float]:
    """PRR with 95% CI. Uses corrected cells for a stable log-SE."""
    prr = (a / (a + b)) / (c / (c + d))
    # SE(ln PRR) = sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
    se = math.sqrt(max(1e-9, 1 / a - 1 / (a + b) + 1 / c - 1 / (c + d)))
    ln = math.log(prr)
    return (round(prr, 3), round(math.exp(ln - _Z * se), 3), round(math.exp(ln + _Z * se), 3))


def _ror_ci(a: float, b: float, c: float, d: float) -> Tuple[float, float, float]:
    """ROR with 95% CI. SE(ln ROR) = sqrt(1/a + 1/b + 1/c + 1/d)."""
    ror = (a * d) / (b * c)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    ln = math.log(ror)
    return (round(ror, 3), round(math.exp(ln - _Z * se), 3), round(math.exp(ln + _Z * se), 3))


# --------------------------------------------------------------------------- #
# Bayesian components
# --------------------------------------------------------------------------- #
def _ic(a: float, expected: float) -> Tuple[float, float]:
    """Information Component (BCPNN) with an approximate 2.5% lower bound (IC025).

    IC = log2(observed / expected). The variance approximation follows Norén et al.
    for the shrinkage estimator with a unit prior.
    """
    obs = a + CORRECTION
    exp = expected + CORRECTION
    ic = math.log2(obs / exp)
    # Norén approximation of Var(IC) on the log2 scale.
    var_ic = (1.0 / (math.log(2) ** 2)) * ((1.0 / obs) + (1.0 / exp))
    ic025 = ic - _Z * math.sqrt(var_ic)
    return round(ic, 3), round(ic025, 3)


def _gamma_prior(counts: List[float], expecteds: List[float]) -> Tuple[float, float]:
    """Method-of-moments Gamma(alpha, beta) prior on the relative reporting ratio.

    Single-component empirical-Bayes approximation of MGPS (DuMouchel 1999). Returns
    (alpha, beta) with prior mean alpha/beta ~= 1 when data are unremarkable.
    """
    ratios = [(n / e) for n, e in zip(counts, expecteds) if e > 0]
    if len(ratios) < 3:
        return 1.0, 1.0  # weak, mean-1 prior when too little data to estimate
    m1 = sum(ratios) / len(ratios)
    var = sum((r - m1) ** 2 for r in ratios) / len(ratios)
    if var <= 1e-9 or m1 <= 0:
        return 2.0, 2.0
    alpha = m1 * m1 / var
    beta = m1 / var
    # keep the prior sane / mildly informative
    alpha = min(max(alpha, 0.2), 50.0)
    beta = min(max(beta, 0.2), 50.0)
    return alpha, beta


def _ebgm(a: float, expected: float, alpha: float, beta: float) -> Tuple[float, float]:
    """EBGM (geometric mean of the posterior) + EB05 (5th percentile).

    Posterior lambda | n,E ~ Gamma(alpha + n, beta + E).
    EBGM = exp(E[ln lambda]) = exp(digamma(alpha+n) - ln(beta+E)).
    EB05 = Gamma-inverse-CDF(0.05; alpha+n) / (beta+E).
    """
    shape = alpha + a
    rate = beta + expected
    if rate <= 0:
        return 0.0, 0.0
    ebgm = math.exp(float(digamma(shape)) - math.log(rate))
    eb05 = float(gammaincinv(shape, 0.05)) / rate
    return round(ebgm, 3), round(eb05, 3)


# --------------------------------------------------------------------------- #
# Strength + SDR flag
# --------------------------------------------------------------------------- #
def _strength(prr: float, chi2: float, count: int) -> str:
    if prr >= 2 and chi2 >= 4 and count >= 3:
        return "STRONG"
    if prr >= 1.5 and count >= 2:
        return "MODERATE"
    return "WEAK"


def _is_sdr(ic025: float, eb05: float, prr_low: float, chi2: float, count: int) -> bool:
    """Signal of disproportionate reporting (any regulator-style criterion met)."""
    if ic025 > 0:                                   # BCPNN (UMC VigiBase standard)
        return True
    if eb05 >= 2.0:                                  # MGPS (FDA) standard
        return True
    if prr_low >= 1.0 and chi2 >= 4 and count >= 3:  # PRR (MHRA/Evans) standard
        return True
    return False


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def compute_signals_from_counts(pair_counts: Counter) -> List[dict]:
    """Same 2×2 math as ``compute_signals``, but takes already-aggregated (drug, event) counts.

    Avoids expanding tens of thousands of FAERS ICSRs into a giant pair list.
    ``a`` is the observed co-report count (post_count), not a scaled surrogate.
    """
    if not pair_counts:
        return []

    total = int(sum(pair_counts.values()))
    if total <= 0:
        return []
    drug_counts: Counter = Counter()
    symptom_counts: Counter = Counter()
    for (drug, symptom), a in pair_counts.items():
        n = int(a or 0)
        if n <= 0:
            continue
        drug_counts[drug] += n
        symptom_counts[symptom] += n

    # First pass: compute observed + expected for the Gamma prior estimation.
    base: List[dict] = []
    counts: List[float] = []
    expecteds: List[float] = []
    for (drug, symptom), a_raw in pair_counts.items():
        a = int(a_raw or 0)
        if a <= 0:
            continue
        drug_total = drug_counts[drug]
        symptom_total = symptom_counts[symptom]
        b = drug_total - a
        c = symptom_total - a
        d = total - a - b - c
        expected = (drug_total * symptom_total) / total if total else 0.0
        base.append({"drug": drug, "symptom": symptom, "a": a, "b": b, "c": c,
                     "d": d, "expected": expected})
        counts.append(float(a))
        expecteds.append(expected)

    if not base:
        return []

    alpha, beta = _gamma_prior(counts, expecteds)

    signals: List[dict] = []
    for row in base:
        a, b, c, d = row["a"], row["b"], row["c"], row["d"]
        aa, bb, cc, dd = a + CORRECTION, b + CORRECTION, c + CORRECTION, d + CORRECTION

        prr, prr_low, prr_high = _prr_ci(aa, bb, cc, dd)
        ror, ror_low, ror_high = _ror_ci(aa, bb, cc, dd)
        chi2 = _chi_square_yates(a, b, c, d)
        ic, ic025 = _ic(a, row["expected"])
        ebgm, eb05 = _ebgm(a, row["expected"], alpha, beta)
        strength = _strength(prr, chi2, a)
        sdr = _is_sdr(ic025, eb05, prr_low, chi2, a)

        signals.append({
            "drug": row["drug"],
            "symptom": row["symptom"],
            "post_count": a,
            "expected": round(row["expected"], 3),
            "prr": prr,
            "prr_ci_low": prr_low,
            "prr_ci_high": prr_high,
            "ror": ror,
            "ror_ci_low": ror_low,
            "ror_ci_high": ror_high,
            "chi_square": chi2,
            "ic": ic,
            "ic025": ic025,
            "ebgm": ebgm,
            "eb05": eb05,
            "strength": strength,
            "sdr_flag": sdr,
        })

    # Rank by the Bayesian lower bound (EB05) then IC025 — the metrics least fooled
    # by small N — falling back to PRR.
    signals.sort(key=lambda s: (s["eb05"], s["ic025"], s["prr"], s["post_count"]),
                 reverse=True)
    return signals


def compute_signals(reports: List[Tuple[str, str]]) -> List[dict]:
    """reports: list of (product_normalized, event_normalized) pairs from AE posts.

    Returns a list of signal dicts with PRR/ROR (+CIs), Yates chi-square, EBGM/EB05,
    IC/IC025, strength tier, and an SDR flag.
    """
    if not reports:
        return []
    return compute_signals_from_counts(Counter(reports))
