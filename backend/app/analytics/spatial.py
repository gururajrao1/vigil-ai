"""Spatial (geographic) cluster detection — Kulldorff-style Poisson scan statistic.

For a given safety signal (drug/device -> event) we ask whether its reports are
geographically CONCENTRATED in a particular country or region beyond what the overall
geographic distribution of ALL adverse-event reports would predict. A concentrated
cluster is an early indicator of a **bad manufacturing batch**, a **counterfeit /
substandard product** in a specific market, or a **regional practice / reporting
issue** — the kind of localized safety problem that a global reporting ratio hides.

Method — a spatial scan statistic (Kulldorff, 1997) with a **Poisson** model:

  * The corpus baseline gives the expected geographic share of reports per area:
        share_z = baseline_z / baseline_total
  * For a signal with ``C`` total reports, the expected count in area ``z`` under the
    null hypothesis of no clustering is
        mu_z = C * share_z
  * Observed ``n_z`` vs expected ``mu_z`` gives a **relative risk**
        RR = n_z / mu_z
  * The Poisson **log-likelihood ratio** for a single candidate area being a
    high-rate cluster is
        LLR = n_z*ln(n_z/mu_z) + (C-n_z)*ln((C-n_z)/(C-mu_z))     when n_z > mu_z
    (and 0 otherwise — only excess-risk clusters are of interest).
  * The **most-likely cluster** is the area maximising the LLR scan score; it is
    *flagged* only when RR and LLR clear sensible thresholds and the observed count
    meets a small minimum (so single stray reports never trip a cluster).

Deterministic, offline, pure-Python (``math`` only) — no GIS / map dependency.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# Cluster-call thresholds (regulator-style, deliberately conservative).
# --------------------------------------------------------------------------- #
MIN_OBSERVED = 5        # need a handful of reports in the area to call a cluster
RR_THRESHOLD = 3.0      # observed >= 3x the expected share in the hotspot
LLR_THRESHOLD = 3.84    # ~chi-square(1df) p<0.05 for the single-area scan statistic


def _round(x: float | None, d: int = 3) -> float | None:
    if x is None:
        return None
    return round(float(x), d)


def _poisson_llr(obs: float, exp: float, total: float) -> float:
    """Kulldorff Poisson log-likelihood ratio for one candidate area.

    Only high-rate clusters (``obs > exp``) contribute; returns 0 otherwise. The
    ``0*ln(0)`` boundary is treated as 0 (its analytic limit).
    """
    if exp <= 0 or obs <= exp:
        return 0.0
    llr = obs * math.log(obs / exp)
    out_obs = total - obs
    out_exp = total - exp
    if out_obs > 0 and out_exp > 0:
        llr += out_obs * math.log(out_obs / out_exp)
    return llr


def detect_cluster(area_counts: Dict[str, float],
                   baseline_counts: Dict[str, float]) -> Optional[dict]:
    """Poisson scan over a single geographic level (country OR region).

    ``area_counts``      = {area: observed reports of THIS signal in the area}.
    ``baseline_counts``  = {area: total AE reports (all signals) in the area} — the
    corpus geographic distribution that defines each area's expected share.

    Returns the most-likely-cluster summary plus the per-area breakdown, or ``None``
    when there is no data. ``cluster`` is True only when RR / LLR / observed all clear
    their thresholds.
    """
    total_obs = float(sum(area_counts.values()))
    baseline_total = float(sum(baseline_counts.values()))
    if total_obs <= 0 or baseline_total <= 0:
        return None

    # Score every area present in the baseline (union with the signal's own areas so a
    # signal seen only in a rare area is still evaluated).
    areas = set(baseline_counts) | set(area_counts)
    by_area: List[dict] = []
    for z in areas:
        obs = float(area_counts.get(z, 0.0))
        share = baseline_counts.get(z, 0.0) / baseline_total
        exp = total_obs * share
        rr = (obs / exp) if exp > 0 else 0.0
        llr = _poisson_llr(obs, exp, total_obs)
        by_area.append({
            "area": z,
            "observed": int(obs),
            "expected": _round(exp, 2),
            "rr": _round(rr, 2),
            "llr": _round(llr, 2),
        })

    # Rank by scan score (LLR), then relative risk, then observed count.
    by_area.sort(key=lambda a: (a["llr"] or 0.0, a["rr"] or 0.0, a["observed"]),
                 reverse=True)
    best = by_area[0]
    is_cluster = (
        best["observed"] >= MIN_OBSERVED
        and (best["rr"] or 0.0) >= RR_THRESHOLD
        and (best["llr"] or 0.0) >= LLR_THRESHOLD
    )
    return {
        "hotspot": best["area"],
        "observed": best["observed"],
        "expected": best["expected"],
        "rr": best["rr"],
        "llr": best["llr"],
        "cluster": is_cluster,
        "total_observed": int(total_obs),
        "n_areas": len(by_area),
        "by_area": by_area,
    }


def assess(signal_area_counts: dict, baseline: dict) -> Optional[dict]:
    """Assess geographic clustering for ONE signal at country + region level.

    ``signal_area_counts`` = {"country": {country: n}, "region": {region: n}}.
    ``baseline``           = {"country": {country: N}, "region": {region: N}}.

    Returns a compact assessment whose primary hotspot is the best COUNTRY cluster
    (falling back to the region level when only the region clusters), or ``None`` when
    neither level shows a cluster. The full country + region breakdowns are always
    included when a cluster is present so the UI can render a ranked per-area view.
    """
    country = detect_cluster(signal_area_counts.get("country", {}),
                             baseline.get("country", {}))
    region = detect_cluster(signal_area_counts.get("region", {}),
                            baseline.get("region", {}))

    country_cluster = bool(country and country["cluster"])
    region_cluster = bool(region and region["cluster"])
    if not country_cluster and not region_cluster:
        return None

    # Prefer the country-level hotspot (more actionable) when it clusters.
    primary = country if country_cluster else region
    level = "country" if country_cluster else "region"
    return {
        "hotspot": primary["hotspot"],
        "level": level,
        "observed": primary["observed"],
        "expected": primary["expected"],
        "rr": primary["rr"],
        "llr": primary["llr"],
        "cluster": True,
        "total_observed": primary["total_observed"],
        "by_area": primary["by_area"],
        "country": country,
        "region": region,
    }


def spatial_clusters(signals_with_geo: List[dict], baseline: dict) -> List[dict]:
    """Batch geographic-cluster assessment for the ``/api/spatial`` endpoint.

    ``signals_with_geo`` = list of {drug, event, product_type, post_count,
    ``area_counts``:{country,region}}. Returns only the signals that flag a cluster,
    each with its hotspot and relative risk, ranked by scan score (LLR) then RR.
    """
    out: List[dict] = []
    for s in signals_with_geo:
        a = assess(s.get("area_counts") or {}, baseline)
        if not a:
            continue
        out.append({
            "drug": s.get("drug"),
            "event": s.get("event"),
            "product_type": s.get("product_type", "drug"),
            "post_count": s.get("post_count"),
            **a,
        })
    out.sort(key=lambda x: (x.get("llr") or 0.0, x.get("rr") or 0.0), reverse=True)
    return out


def reference() -> dict:
    """Method + threshold description (for a reference view / tooltips)."""
    return {
        "method": "Kulldorff spatial scan statistic (Poisson model)",
        "thresholds": {
            "min_observed": MIN_OBSERVED,
            "relative_risk": RR_THRESHOLD,
            "log_likelihood_ratio": LLR_THRESHOLD,
        },
        "note": "Compares a signal's observed count per area against the expected "
                "count under the corpus-wide geographic distribution of all AE "
                "reports. Geolocation is post-level and coarse (country / region).",
    }
