"""Competition-bias masking / unmasking for disproportionality signals.

Dominant drug–event mass can suppress PRR/IC for other products sharing the
same event (Pariente/Maignen; ENCePP Ch.11).

Remine removes the *masker drugs' reports* from the 2×2 table (competition-bias
unmasking), then recomputes DMA for the target pair — the actionable sensitivity
analysis analysts expect.
"""
from __future__ import annotations

from collections import Counter
from typing import List, Optional, Set, Tuple

from .disproportionality import compute_signals


def _pair_metrics(
    reports: List[Tuple[str, str]], drug: str, event: str
) -> Optional[dict]:
    if not reports:
        return None
    signals = compute_signals(reports)
    d_l, e_l = drug.lower(), event.lower()
    for s in signals:
        if s["drug"].lower() == d_l and s["symptom"].lower() == e_l:
            return s
    return None


def _event_matches(report_event: str, target_event: str) -> bool:
    a, b = (report_event or "").lower().strip(), (target_event or "").lower().strip()
    if not a or not b:
        return False
    if a == b:
        return True
    # Soft match: shared significant token (e.g. myocarditis / myocardial)
    if len(b) >= 5 and (b in a or a in b):
        return True
    return False


def analyze_masking(
    reports: List[Tuple[str, str]],
    drug: str,
    event: str,
    *,
    top_n: int = 10,
) -> dict:
    """Rank competitor drugs on the same (or soft-matched) event."""
    drug_l = (drug or "").lower()
    event_pairs = [(d, e) for d, e in reports if _event_matches(e, event)]
    # Prefer exact event match when available
    exact = [(d, e) for d, e in event_pairs if e.lower() == (event or "").lower()]
    if exact:
        event_pairs = exact

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
            "can_remine": False,
            "suggested_exclude": [],
            "verdict": "No corpus reports match this event — remine is not available.",
            "note": "No reports for this event in the current project corpus.",
            "method": "event-share competition bias (Pariente/Maignen-style)",
        }

    by_drug = Counter(d for d, _ in event_pairs)
    target_count = 0
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
        pressure = cnt / max(target_count, 1)
        # Selectable whenever another drug reports the same event
        likely = share >= 0.10 or pressure >= 1.0 or cnt >= target_count
        maskers.append({
            "drug": other,
            "count": int(cnt),
            "event_share": round(share, 4),
            "vs_target_ratio": round(pressure, 3),
            "likely_masker": likely,
        })
        if len(maskers) >= top_n:
            break

    top_share = maskers[0]["event_share"] if maskers else 0.0
    if top_share >= 0.35 and target_share < 0.40:
        risk = "high"
    elif top_share >= 0.15 or any(m["likely_masker"] for m in maskers):
        risk = "moderate"
    elif maskers:
        risk = "low"
    else:
        risk = "none"

    baseline = _pair_metrics(reports, drug, event)
    suggested = [m["drug"] for m in maskers if m["likely_masker"]][:3]
    if not suggested and maskers:
        suggested = [maskers[0]["drug"]]

    if not maskers:
        verdict = (
            f"{drug} accounts for all {total_event} reports of this event in the corpus — "
            "no competing product to unmask against. Try a signal that shares an event "
            "with other products (e.g. suicidal ideation, hypertension, device loosening)."
        )
    elif risk in ("high", "moderate"):
        names = ", ".join(suggested) if suggested else maskers[0]["drug"]
        verdict = (
            f"Competition bias possible: {names} also drive this event. "
            "Remine without those products to see if this signal strengthens."
        )
    else:
        verdict = (
            f"{len(maskers)} other product(s) also report this event. "
            "Remine to test sensitivity to competition bias."
        )

    return {
        "drug": drug,
        "event": event,
        "event_total": total_event,
        "target_count": int(target_count),
        "target_share": round(target_share, 4),
        "maskers": maskers,
        "masking_risk": risk,
        "can_remine": bool(maskers),
        "suggested_exclude": suggested,
        "verdict": verdict,
        "baseline": {
            "prr": baseline.get("prr") if baseline else None,
            "prr_ci_low": baseline.get("prr_ci_low") if baseline else None,
            "ror": baseline.get("ror") if baseline else None,
            "ic025": baseline.get("ic025") if baseline else None,
            "eb05": baseline.get("eb05") if baseline else None,
            "chi_square": baseline.get("chi_square") if baseline else None,
            "post_count": baseline.get("post_count") if baseline else target_count,
            "sdr_flag": bool(baseline.get("sdr_flag")) if baseline else False,
            "strength": baseline.get("strength") if baseline else None,
        },
        "note": (
            "Remine removes the selected competitors' reports from the disproportionality "
            "table (competition-bias unmasking), then recomputes PRR/IC/EB05 for this pair."
        ),
        "method": "remove-masker-reports remine (Pariente/Maignen-style)",
    }


def remine_unmasked(
    posts: List[dict],
    drug: str,
    event: str,
    exclude_drugs: List[str],
    *,
    full_reports: Optional[List[Tuple[str, str]]] = None,
) -> dict:
    """Recompute DMA after removing all reports of selected masker drugs."""
    excl: Set[str] = {d.strip().lower() for d in exclude_drugs if d and d.strip()}

    baseline_reports = full_reports
    if baseline_reports is None:
        baseline_reports = []
        for p in posts:
            for d in p.get("drugs") or []:
                for e in p.get("events") or []:
                    baseline_reports.append((d, e))

    baseline = analyze_masking(baseline_reports, drug, event)
    if not excl and baseline.get("suggested_exclude"):
        excl = {d.lower() for d in baseline["suggested_exclude"]}

    # Competition-bias remine: drop EVERY report row whose drug is a masker
    unmasked_reports = [
        (d, e) for d, e in baseline_reports if d.lower() not in excl
    ]
    remine = _pair_metrics(unmasked_reports, drug, event)

    b = baseline.get("baseline") or {}
    delta = None
    if remine and b.get("prr") is not None and remine.get("prr") is not None:
        delta = {
            "prr_delta": round(remine["prr"] - (b["prr"] or 0), 3),
            "ic025_delta": round((remine.get("ic025") or 0) - (b.get("ic025") or 0), 3),
            "eb05_delta": round((remine.get("eb05") or 0) - (b.get("eb05") or 0), 3),
            "count_delta": int(remine.get("post_count") or 0) - int(b.get("post_count") or 0),
        }

    revealed = False
    attenuated = False
    if remine:
        was_sdr = bool(b.get("sdr_flag"))
        now_sdr = bool(remine.get("sdr_flag"))
        prr_up = (remine.get("prr") or 0) > (b.get("prr") or 0) * 1.15
        prr_down = (remine.get("prr") or 0) < (b.get("prr") or 0) * 0.85
        revealed = (now_sdr and not was_sdr) or prr_up
        attenuated = (was_sdr and not now_sdr) or prr_down

    if not excl:
        interpretation = "No maskers selected — metrics unchanged."
    elif remine is None:
        interpretation = (
            "After removing maskers, this pair vanished from the residual corpus "
            "(no remaining reports). Competition bias cannot be assessed this way."
        )
    elif revealed:
        interpretation = (
            f"Signal strengthened after removing {', '.join(sorted(excl))}. "
            "Competition bias may have been suppressing this pair — escalate for review."
        )
    elif attenuated:
        interpretation = (
            f"Signal weakened after removing {', '.join(sorted(excl))}. "
            "The association may have been inflated by shared reporting patterns."
        )
    else:
        interpretation = (
            f"Metrics stable after removing {', '.join(sorted(excl))}. "
            "Competition bias does not appear to drive this signal."
        )

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
        "signal_attenuated": attenuated,
        "interpretation": interpretation,
        "masking_risk": baseline.get("masking_risk"),
        "maskers": baseline.get("maskers"),
        "verdict": baseline.get("verdict"),
        "disclaimer": (
            "Unmasked metrics are a corpus sensitivity analysis — not a regulatory decision. "
            "Prototype; not for clinical use."
        ),
    }
