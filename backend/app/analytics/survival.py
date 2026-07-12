"""Cox proportional-hazards surrogate for time-to-AE onset.

Implements a **single-covariate Cox PH estimator** using pure numpy + scipy,
without any external survival-analysis package (no lifelines, no statsmodels
survival extensions).

Context / disclaimer
--------------------
This is an *illustrative social-listening surrogate*, NOT a clinical hazard ratio.
Social-media data lacks:
  - true cohort denominators (we don't know who was exposed but didn't post)
  - vaccination / treatment start dates (anchor = first mention)
  - censoring dates (all supporting posts are "events" in our model)

What we compute
---------------
For a signal (drug, event):
  * **Exposed group** — the signal's own supporting posts.
    Time-to-event = days from the signal's ``earliest_post_at`` anchor to
    each supporting-post timestamp.
  * **Unexposed (comparator) group** — AE posts NOT associated with this drug
    (i.e. not in the signal's supporting-post set).
    Same anchor.

We then fit a binary-covariate Cox partial-likelihood model
(x=1 exposed, x=0 unexposed) using Newton-Raphson optimisation.
Breslow approximation handles tied event times.

Statistical details
-------------------
Log partial likelihood (Breslow):
    L(β) = Σ_j [ m₁_j · β  −  d_j · ln(n₀_j + n₁_j · e^β) ]

  where j indexes unique event times, d_j = total events at time t_j,
  m₁_j = exposed events at t_j, n₀_j/n₁_j = risk set sizes.

Score  U(β) = dL/dβ = Σ_j [ m₁_j − d_j · n₁_j·e^β / (n₀_j + n₁_j·e^β) ]
Info   I(β) = Σ_j [ d_j · n₁_j·n₀_j·e^β / (n₀_j + n₁_j·e^β)² ]

Newton-Raphson:  β ← β + U(β)/I(β)

HR = exp(β̂),  Var(β̂) = 1/I(β̂),  95% CI = exp(β̂ ± 1.96·SE)

The log-rank statistic (score test at β=0):  U(0)² / I(0)  ~  χ²(1 df)
"""
from __future__ import annotations

import math
import random
from datetime import datetime
from typing import List, Optional

import numpy as np
from scipy import stats as scipy_stats

_DISCLAIMER = (
    "Illustrative social-listening surrogate — NOT a clinical hazard ratio. "
    "Anchor = earliest post for this drug–event signal. "
    "Exposed = signal's own supporting posts; unexposed = other-drug AE posts. "
    "All posts treated as observed events (no censoring). "
    "Breslow approximation for tied times."
)

_MAX_COMPARATORS = 300  # cap comparator sample for performance


def _standard_normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _cox_partial_likelihood(
    exposed_times: List[float],
    unexposed_times: List[float],
) -> dict:
    """Fit single-covariate Cox PH model (x=1 exposed, x=0 unexposed).

    All times assumed positive (days). Returns a result dict.
    """
    n_exp = len(exposed_times)
    n_unexp = len(unexposed_times)
    n_total = n_exp + n_unexp

    if n_total < 3:
        return {
            "hr": None, "hr_ci": None, "hr_p": None, "logrank_p": None,
            "n_exposed": n_exp, "n_unexposed": n_unexp,
            "sufficient": False,
            "note": "insufficient data (fewer than 3 events)",
        }

    # Build sorted arrays
    times_arr = np.array(exposed_times + unexposed_times, dtype=np.float64)
    x_arr = np.array([1.0] * n_exp + [0.0] * n_unexp, dtype=np.float64)
    times_arr = np.maximum(times_arr, 0.01)

    order = np.argsort(times_arr, kind="stable")
    times_arr = times_arr[order]
    x_arr = x_arr[order]

    unique_times = np.unique(times_arr)

    def _risk_counts(t: float):
        in_risk = times_arr >= t
        at_t = times_arr == t
        n1 = float(np.sum(x_arr[in_risk] == 1.0))
        n0 = float(np.sum(x_arr[in_risk] == 0.0))
        d = float(np.sum(at_t))
        m1 = float(np.sum(at_t & (x_arr == 1.0)))
        return n1, n0, d, m1

    def _score_and_info(beta: float):
        U = 0.0
        I = 0.0
        eb = math.exp(min(max(beta, -20.0), 20.0))
        for t in unique_times:
            n1, n0, d, m1 = _risk_counts(t)
            denom = n0 + n1 * eb
            if denom < 1e-12:
                continue
            w = n1 * eb / denom
            U += m1 - d * w
            I += d * n1 * n0 * eb / (denom * denom)
        return U, I

    # Log-rank test (score test at β=0)
    U0, I0 = _score_and_info(0.0)
    logrank_p = 1.0
    if I0 > 1e-10:
        chi2_lr = float(U0 ** 2 / I0)
        logrank_p = float(1.0 - scipy_stats.chi2.cdf(chi2_lr, df=1))

    # Newton-Raphson for β̂
    beta = 0.0
    for _ in range(50):
        U, I = _score_and_info(beta)
        if abs(I) < 1e-12:
            break
        step = U / I
        step = max(min(step, 2.0), -2.0)  # clip to prevent divergence
        beta += step
        if abs(step) < 1e-8:
            break

    _, I_hat = _score_and_info(beta)

    if I_hat < 1e-12:
        return {
            "hr": None, "hr_ci": None, "hr_p": None,
            "logrank_p": round(logrank_p, 6),
            "n_exposed": n_exp, "n_unexposed": n_unexp,
            "sufficient": False,
            "note": "degenerate risk sets (zero variation in covariate within risk set)",
        }

    se_beta = 1.0 / math.sqrt(I_hat)

    # Quasi-complete separation (e.g. all events in one group) drives beta / se_beta
    # to extreme values where exp() overflows and the HR is not meaningfully estimable.
    if abs(beta) > 20.0 or se_beta > 20.0:
        return {
            "hr": None, "hr_ci": None, "hr_p": None,
            "logrank_p": round(logrank_p, 6),
            "n_exposed": n_exp, "n_unexposed": n_unexp,
            "sufficient": False,
            "note": "quasi-complete separation — hazard ratio unstable/undefined "
                    "(events concentrated in one group).",
        }

    # Clamp exponents defensively so a large-but-finite estimate never overflows.
    def _safe_exp(x: float) -> float:
        return math.exp(max(min(x, 30.0), -30.0))

    hr = _safe_exp(beta)
    hr_lo = _safe_exp(beta - 1.96 * se_beta)
    hr_hi = _safe_exp(beta + 1.96 * se_beta)
    z = beta / se_beta
    p_wald = 2.0 * (1.0 - _standard_normal_cdf(abs(z)))

    return {
        "hr": round(hr, 4),
        "hr_ci": [round(hr_lo, 4), round(hr_hi, 4)],
        "hr_p": round(p_wald, 6),
        "logrank_p": round(logrank_p, 6),
        "n_exposed": n_exp,
        "n_unexposed": n_unexp,
        "beta": round(beta, 6),
        "se_beta": round(se_beta, 6),
        "sufficient": True,
        "note": _DISCLAIMER,
    }


def compute_hazard_ratio(
    signal_timestamps: List[datetime],
    comparator_timestamps: List[datetime],
    anchor: Optional[datetime] = None,
) -> dict:
    """Compute the Cox PH surrogate HR for a (drug, event) signal.

    Parameters
    ----------
    signal_timestamps:
        Posting timestamps of the signal's own supporting posts (exposed group).
    comparator_timestamps:
        Posting timestamps of AE posts NOT linked to this drug (unexposed group).
    anchor:
        Anchor datetime (signal's ``earliest_post_at``).  Defaults to the
        minimum of *signal_timestamps*.

    Returns
    -------
    dict with keys: hr, hr_ci, hr_p, hr_elevated, hr_json
    """
    _null = {"hr": None, "hr_ci": None, "hr_p": None, "hr_elevated": False,
             "hr_json": {"sufficient": False, "note": "insufficient data (no signal timestamps)"}}
    if not signal_timestamps:
        return _null

    if anchor is None:
        anchor = min(signal_timestamps)

    def _to_days(ts: datetime) -> float:
        try:
            secs = (ts - anchor).total_seconds()
            return secs / 86400.0
        except Exception:
            return 0.0

    exposed_times = [max(0.01, _to_days(ts)) for ts in signal_timestamps]

    # Build comparator, filtered to >= anchor (no left-truncation issues)
    raw_comp = [_to_days(ts) for ts in comparator_timestamps]
    comp_filtered = [max(0.01, d) for d in raw_comp if d >= 0.0]

    # Sample comparators to keep computation tractable
    if len(comp_filtered) > _MAX_COMPARATORS:
        rng = random.Random(len(exposed_times))
        comp_filtered = rng.sample(comp_filtered, _MAX_COMPARATORS)

    result = _cox_partial_likelihood(exposed_times, comp_filtered)

    hr_elevated = (
        result.get("sufficient", False)
        and result.get("hr_ci") is not None
        and result["hr_ci"][0] > 1.0
    )

    return {
        "hr": result.get("hr"),
        "hr_ci": result.get("hr_ci"),
        "hr_p": result.get("hr_p"),
        "hr_elevated": hr_elevated,
        "hr_json": result,
    }
