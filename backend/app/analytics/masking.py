"""Competition-bias masking / unmasking for disproportionality signals.

Dominant drug–event mass can suppress PRR/IC for other products sharing the
same event (Pariente/Maignen; ENCePP Ch.11; SDF 2025 fusion literature).

This module:
  1. Ranks top masker drugs for a target (drug, event) by event-share
  2. Optionally remines DMA after removing posts that mention those maskers

Deterministic, offline, no network.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from .corpus import reports_from_posts_excluding_maskers
from .disproportionality import compute_signals

CORRECTION = 0.5


def _pair_metrics(
    reports: List[Tuple[str, str]], drug: str, event: str
) -> Optional[dict]:
    """Compute a single-pair DMA row from a report list (or None if absent)."""
    if not reports:
        return None
    signals = compute_signals(reports)
    d_l, e_l = drug.lower(), event.lower()
    for s in signals:
        if s["drug"].lower() == d_l and s["symptom"].lower() == e_l:
            return s
    # Pair may have been eliminated entirely after unmasking
    return None


def analyze_masking(
    reports: List[Tuple[str, str]],
    drug: str,
    event: str,
    *,
    top_n: int = 8,
) -> dict:
    """Build a masking report for (drug, event).

    Masking ratio for competitor M on event E:
        share_M = count(M, E) / count(*, E)
    A high share from a non-target drug indicates competition bias risk.
    """
    event_l = event.lower()
    drug_l = drug.lower()

    event_pairs = [(d, e) for d, e in reports if e.lower() == event_l]
    total_event = len(event_pairs)
    if total_event == 0:
        return {
            "drug": drug,
            "event": event,
            "event_total": 0,
            "target_count": 0,
            "target_share": 0.0,
            "maskers": [],
            "masking_risk": "none",
            "note": "No reports for this event in the current corpus.",
        }

    by_drug = Counter(d for d, _ in event_pairs)
    target_count = by_drug.get(drug, 0)
    # case-insensitive fallback
    if target_count == 0:
        for k, v in by_drug.items():
            if k.lower() == drug_l:
                target_count = v
                drug = k
                break

    target_share = target_count / total_event if total_event else 0.0

    maskers = []
    for other, cnt in by_drug.most_common():
        if other.lower() == drug_l:
            continue
        share = cnt / total_event
        # Relative masking pressure: how much larger is competitor vs target
        pressure = (cnt / max(target_count, 1))
        maskers.append({
            "drug": other,
            "count": int(cnt),
            "event_share": round(share, 4),
            "vs_target_ratio": round(pressure, 3),
            "likely_masker": share >= 0.15 and pressure >= 1.5,
        })
        if len(maskers) >= top_n:
            break

    top_share = maskers[0]["event_share"] if maskers else 0.0
    if top_share >= 0.35 and target_share < 0.25:
        risk = "high"
    elif top_share >= 0.20 or any(m["likely_masker"] for m in maskers):
        risk = "moderate"
    elif maskers:
        risk = "low"
    else:
        risk = "none"

    baseline = _pair_metrics(reports, drug, event)

    return {
        "drug": drug,
        "event": event,
        "event_total": total_event,
        "target_count": int(target_count),
        "target_share": round(target_share, 4),
        "maskers": maskers,
        "masking_risk": risk,
        "baseline": {
            "prr": baseline.get("prr") if baseline else None,
            "prr_ci_low": baseline.get("prr_ci_low") if baseline else None,
            "ror": baseline.get("ror") if baseline else None,
            "ic025": baseline.get("ic025") if baseline else None,
            "eb05": baseline.get("eb05") if baseline else None,
            "chi_square": baseline.get("chi_square") if baseline else None,
            "post_count": baseline.get("post_count") if baseline else target_count,
            "sdr_flag": baseline.get("sdr_flag") if baseline else False,
            "strength": baseline.get("strength") if baseline else None,
        },
        "note": (
            "Masking (competition bias): a dominant drug–event pair can suppress "
            "disproportionality for other products sharing the same event. "
            "Use remine to drop posts mentioning selected maskers and recompute."
        ),
        "method": "event-share competition bias (Pariente/Maignen-style)",
    }


def remine_unmasked(
    posts: List[dict],
    drug: str,
    event: str,
    exclude_drugs: List[str],
    *,
    full_reports: Optional[List[Tuple[str, str]]] = None,
) -> dict:
    """Recompute DMA for (drug, event) after removing masker-contaminated posts."""
    excl: Set[str] = {d.strip() for d in exclude_drugs if d and d.strip()}
    baseline_reports = full_reports
    if baseline_reports is None:
        baseline_reports = []
        for p in posts:
            for d in p["drugs"]:
                for e in p["events"]:
                    baseline_reports.append((d, e))

    baseline = analyze_masking(baseline_reports, drug, event)
    unmasked_reports = reports_from_posts_excluding_maskers(posts, excl)
    remine = _pair_metrics(unmasked_reports, drug, event)

    b = baseline.get("baseline") or {}
    delta = None
    if remine and b.get("prr") is not None and remine.get("prr") is not None:
        delta = {
            "prr_delta": round(remine["prr"] - (b["prr"] or 0), 3),
            "ic025_delta": round(
                (remine.get("ic025") or 0) - (b.get("ic025") or 0), 3
            ),
            "eb05_delta": round(
                (remine.get("eb05") or 0) - (b.get("eb05") or 0), 3
            ),
            "count_delta": int(remine.get("post_count") or 0)
            - int(b.get("post_count") or 0),
        }

    revealed = False
    if remine:
        was_sdr = bool(b.get("sdr_flag"))
        now_sdr = bool(remine.get("sdr_flag"))
        prr_up = (remine.get("prr") or 0) > (b.get("prr") or 0) * 1.2
        revealed = (now_sdr and not was_sdr) or prr_up

    return {
        "drug": drug,
        "event": event,
        "excluded_maskers": sorted(excl),
        "reports_before": len(baseline_reports),
        "reports_after": len(unmasked_reports),
        "baseline": b,
        "unmasked": remine,
        "delta": delta,
        "signal_strengthened": revealed,
        "masking_risk": baseline.get("masking_risk"),
        "maskers": baseline.get("maskers"),
        "disclaimer": (
            "Unmasked metrics are a sensitivity analysis on the VigilAI corpus, "
            "not a regulatory decision. Prototype / teaching use only."
        ),
    }
