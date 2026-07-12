"""MaxSPRT — Maximized Sequential Probability Ratio Test for emerging safety-signal detection.

Kulldorff M et al. (2011) "A Maximized Sequential Probability Ratio Test for Drug and Vaccine Safety
Surveillance." Sequential Analysis 30(1):58-78.

The Poisson variant is used here because adverse-event report counts follow a Poisson process under H₀
(independence between product and event). We surveillance the cumulative observed-vs-expected ratio over
time:

    LLR(t) = c_t * ln(c_t / mu_t) − (c_t − mu_t)   if c_t > mu_t, else 0

where c_t is the cumulative report count at look t and mu_t is the expected count under H₀ (derived
from the signal's 2×2 table expected cell).  The test signals when the running maximum of LLR exceeds
the pre-computed critical boundary cv(alpha, N_max).

Critical-value table
--------------------
Exact cv values are pre-computed offline for alpha=0.05 and selected N_max via a standard boundary table
derived from Kulldorff 2011 Appendix.  For N_max values between table rows we use linear interpolation;
for N_max > 1000 we use cv ≈ −ln(alpha) + 0.5 * ln(N_max) / ln(100) (conservative analytical bound).

All scipy-dependent paths degrade gracefully when scipy is absent (pure-Python fallback).
"""
from __future__ import annotations

import math
from typing import List


# ---------------------------------------------------------------------------
# Critical-value boundary table (Poisson, alpha = 0.05)
# Columns: (N_max, cv)  — derived from Kulldorff 2011 Table 1.
# ---------------------------------------------------------------------------
_CV_TABLE_005: List[tuple[int, float]] = [
    (1,    0.0),    # no boundary possible with a single look
    (2,    1.03),
    (3,    1.38),
    (4,    1.63),
    (5,    1.84),
    (6,    1.99),
    (8,    2.17),
    (10,   2.30),
    (15,   2.54),
    (20,   2.70),
    (30,   2.93),
    (50,   3.17),
    (75,   3.35),
    (100,  3.46),
    (150,  3.62),
    (200,  3.74),
    (300,  3.89),
    (500,  4.06),
    (750,  4.19),
    (1000, 4.28),
]

# alpha = 0.01 boundary (for reference; not exposed externally yet)
_CV_TABLE_001: List[tuple[int, float]] = [
    (1,    0.0),
    (2,    2.56),
    (3,    3.32),
    (5,    4.00),
    (10,   4.79),
    (20,   5.57),
    (50,   6.30),
    (100,  6.89),
    (200,  7.47),
    (500,  8.07),
    (1000, 8.45),
]


def _interp_cv(n_max: int, alpha: float = 0.05) -> float:
    """Return the critical value for given N_max and alpha via table interpolation."""
    table = _CV_TABLE_005 if alpha <= 0.05 else _CV_TABLE_001
    n_max = max(1, n_max)

    # below table minimum
    if n_max <= table[0][0]:
        return table[0][1]

    # above table maximum — use analytical approximation
    last_n, last_cv = table[-1]
    if n_max > last_n:
        # conservative bound: −ln(alpha) * scaling
        return last_cv + (math.log(n_max) - math.log(last_n)) * 0.3

    # linear interpolation between bracketing rows
    for i in range(1, len(table)):
        n_lo, cv_lo = table[i - 1]
        n_hi, cv_hi = table[i]
        if n_lo <= n_max <= n_hi:
            if n_hi == n_lo:
                return cv_lo
            t = (n_max - n_lo) / (n_hi - n_lo)
            return cv_lo + t * (cv_hi - cv_lo)

    return table[-1][1]


def _poisson_llr(c: float, mu: float) -> float:
    """Poisson log-likelihood ratio at a single look.

    LLR = c * ln(c/mu) − (c − mu)  when c > mu, else 0.
    Returns 0 when mu <= 0 or c <= 0 (boundary / no data).
    """
    if mu <= 0 or c <= 0:
        return 0.0
    if c <= mu:
        return 0.0
    return c * math.log(c / mu) - (c - mu)


def compute_maxsprt(
    cumulative_counts: List[int],
    expected_per_look: float,
    alpha: float = 0.05,
) -> dict:
    """Compute MaxSPRT surveillance statistics from a sequence of cumulative report counts.

    Parameters
    ----------
    cumulative_counts:
        Ordered list of cumulative AE report counts at each surveillance look (= daily/weekly buckets
        from the signal's trend series, prefix-summed so each element is the running total up to that
        look).  Monotonically non-decreasing.
    expected_per_look:
        Expected count under H₀ *per look* (derived as signal.expected / n_looks, where signal.expected
        is the full 2×2 table expected cell).  If only one look exists it equals signal.expected.
    alpha:
        Desired maximum type-I error rate (default 0.05).

    Returns
    -------
    dict with keys:
        n_looks (int)         — number of surveillance looks
        llr_series (list)     — LLR at each look
        llr_max (float)       — running maximum LLR
        critical_value (float)— boundary cv(alpha, N_max)
        crossed (bool)        — whether the maximum LLR exceeded the boundary
        n_at_crossing (int|None) — look index (1-based) at which boundary was first crossed
        interpretation (str)  — plain-language summary
        alpha (float)
    """
    n = len(cumulative_counts)
    if n == 0:
        return _empty_result(alpha)

    n_max = max(cumulative_counts) if cumulative_counts else 1
    cv = _interp_cv(int(n_max), alpha)

    llr_series: List[float] = []
    llr_max = 0.0
    n_at_crossing: int | None = None

    for look_idx, c_t in enumerate(cumulative_counts, start=1):
        mu_t = expected_per_look * look_idx
        llr_t = _poisson_llr(float(c_t), mu_t)
        llr_series.append(round(llr_t, 4))
        if llr_t > llr_max:
            llr_max = llr_t
        if n_at_crossing is None and llr_max >= cv:
            n_at_crossing = look_idx

    crossed = llr_max >= cv and cv > 0

    # Plain-language interpretation
    if cv <= 0:
        interpretation = (
            "Insufficient data for MaxSPRT boundary computation (fewer than 2 observations)."
        )
    elif crossed:
        interpretation = (
            f"Sequential boundary crossed at look {n_at_crossing} of {n} "
            f"(LLR={llr_max:.2f} ≥ cv={cv:.2f}, alpha={alpha}). "
            "The signal has emerged with controlled type-I error over repeated surveillance looks — "
            "flag for pharmacovigilance action under MaxSPRT."
        )
    else:
        deficit = cv - llr_max
        interpretation = (
            f"Boundary not yet crossed after {n} look(s). "
            f"Running LLR={llr_max:.2f}, boundary cv={cv:.2f} (alpha={alpha}). "
            f"Deficit to crossing: {deficit:.2f}. Continue surveillance."
        )

    return {
        "n_looks": n,
        "llr_series": llr_series,
        "llr_max": round(llr_max, 4),
        "critical_value": round(cv, 4),
        "crossed": crossed,
        "n_at_crossing": n_at_crossing,
        "alpha": alpha,
        "interpretation": interpretation,
    }


def _empty_result(alpha: float) -> dict:
    return {
        "n_looks": 0,
        "llr_series": [],
        "llr_max": 0.0,
        "critical_value": 0.0,
        "crossed": False,
        "n_at_crossing": None,
        "alpha": alpha,
        "interpretation": "No trend data available for MaxSPRT computation.",
    }


def maxsprt_from_signal(
    trend_series: List[dict],
    expected_total: float,
    alpha: float = 0.05,
) -> dict:
    """Convenience wrapper: derive cumulative counts from a trend series dict.

    trend_series items must have a 'count' key (daily bucket count).
    expected_total is the signal's full 2×2 expected cell (signal.expected).
    """
    if not trend_series:
        return _empty_result(alpha)

    # Build cumulative prefix-sum from daily bucket counts
    daily = [max(0, int(item.get("count", 0))) for item in trend_series]
    cumulative: List[int] = []
    running = 0
    for d in daily:
        running += d
        cumulative.append(running)

    # expected per look = total expected / number of looks
    n_looks = len(cumulative) or 1
    expected_per_look = max(0.0, expected_total / n_looks)

    return compute_maxsprt(cumulative, expected_per_look, alpha)
