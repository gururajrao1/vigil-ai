"""Verdict / takeaway layer for Signal Copilot.

Turns raw DMA numbers into instant good / bad / mixed conclusions so
non-PV readers do not have to decode jargon.
"""
from __future__ import annotations

from typing import Any


def _g(sig: Any, key: str, default: Any = None) -> Any:
    if isinstance(sig, dict):
        return sig.get(key, default)
    return getattr(sig, key, default)


def _num(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _n(sig: Any) -> int:
    try:
        return int(_g(sig, "post_count") or _g(sig, "ae_count") or 0)
    except (TypeError, ValueError):
        return 0


def _product(sig: Any) -> str:
    return _g(sig, "drug") or _g(sig, "product_name") or "this product"


def _event(sig: Any) -> str:
    md = _g(sig, "meddra") or {}
    if isinstance(md, dict) and md.get("pt"):
        return md["pt"]
    return _g(sig, "symptom") or _g(sig, "event_term") or "this event"


def build_bottom_line(sig: Any) -> dict[str, Any]:
    """One-screen conclusion for the whole Signal Detail page."""
    product = _product(sig)
    event = _event(sig)
    n = _n(sig)
    strength = (_g(sig, "strength") or "WEAK").upper()
    sdr = bool(_g(sig, "sdr_flag"))
    prr = _num(_g(sig, "prr"))
    eb05 = _num(_g(sig, "eb05"))
    ic025 = _num(_g(sig, "ic025"))
    chi2 = _num(_g(sig, "chi_square") if _g(sig, "chi_square") is not None else _g(sig, "chi2"))
    cal_ok = bool(_g(sig, "calibrated_signal"))
    cal_p = _num(_g(sig, "calibrated_p"))
    spike = bool(_g(sig, "spike_flag") or _g(sig, "spike"))
    crossed = bool(_g(sig, "maxsprt_crossed"))
    mx = _g(sig, "maxsprt") or {}
    if isinstance(mx, dict) and mx.get("crossed"):
        crossed = True
    trust = (_g(sig, "trust_label") or "").lower()
    well_doc = bool(_g(sig, "well_documented"))
    comp = _g(sig, "completeness_detail") or {}
    mean_c = _num(comp.get("mean_completeness") if isinstance(comp, dict) else None)
    if mean_c is None:
        mean_c = _num(_g(sig, "completeness"))
    if mean_c is not None and mean_c < 0.5:
        well_doc = False
    who = _g(sig, "who_umc") or "Unassessable"
    tri = _g(sig, "triangulation") or {}
    urgency = (tri.get("urgency_tier") if isinstance(tri, dict) else None) or ""

    alarms: list[str] = []
    coolers: list[str] = []

    if sdr or strength == "STRONG" or (eb05 is not None and eb05 >= 2):
        alarms.append(
            f"Screening stats are loud (strength {strength}"
            f"{', SDR flag on' if sdr else ''}"
            f"{f', EB05={eb05:.2f}' if eb05 is not None else ''})."
        )
    if prr is not None and prr >= 10 and n < 10:
        coolers.append(
            f"PRR looks enormous ({prr:.0f}×) but only {n} report(s) — tiny samples "
            "inflate ratios into scary-looking numbers."
        )
    elif prr is not None and prr >= 2 and n >= 3:
        alarms.append(f"PRR {prr:.1f} with n={n} clears a classic screening bar.")
    if ic025 is not None and ic025 <= 0:
        coolers.append(
            f"IC025 is {ic025:.2f} (not > 0) — the cautious Bayesian vote is NOT convinced yet."
        )
    if eb05 is not None and eb05 >= 2 and ic025 is not None and ic025 <= 0:
        coolers.append("EB05 and IC025 disagree — mixed Bayesian picture, not a slam dunk.")
    if cal_p is not None and not cal_ok:
        coolers.append(
            f"Empirical calibration failed (p≈{cal_p:.3f}) — this may sit in the noise floor."
        )
    elif cal_ok:
        alarms.append("Survives empirical calibration — harder to dismiss as pure noise.")
    if not well_doc or (mean_c is not None and mean_c < 0.5):
        coolers.append(
            f"Supporting posts are poorly documented"
            f"{f' (completeness {mean_c:.2f}/1.00)' if mean_c is not None else ''} — thin evidence to act on."
        )
    if trust in ("low", "sybil"):
        coolers.append(f"Trust label is '{trust}' — counts may be gamed or coordinated.")
    if spike:
        alarms.append("Recent spike in talk — something changed in the chatter.")
    if crossed:
        alarms.append("MaxSPRT boundary crossed — sequential alarm is on.")
    if who in ("Certain", "Probable"):
        alarms.append(f"Causality lean is {who}.")
    elif who in ("Unlikely", "Unassessable"):
        coolers.append(f"Causality is {who} — stories do not clearly pin the product.")
    if "CRITICAL" in urgency or "HIGH" in urgency:
        alarms.append(f"Triangulation urgency: {urgency.replace('_', ' ')}.")
    elif urgency == "INSUFFICIENT":
        coolers.append("Triangulation is insufficient across sources.")

    # Tone scoring
    score = len(alarms) - len(coolers)
    if n <= 2 and strength == "WEAK" and not sdr:
        tone = "reassuring"
        label = "Low concern for now"
        headline = (
            f"{product} → {event}: weak / sparse pattern. No need to escalate on this alone."
        )
    elif score >= 2 and len(coolers) == 0:
        tone = "concerning"
        label = "Elevated concern"
        headline = (
            f"{product} → {event}: several independent alarms agree. Prioritize human review."
        )
    elif score >= 1 and coolers:
        tone = "mixed"
        label = "Mixed — loud but fragile"
        headline = (
            f"{product} → {event}: screening numbers look scary, but quality / calibration / "
            f"sample-size caveats pull the other way. Watch closely; do not treat as proven harm."
        )
    elif coolers and not alarms:
        tone = "reassuring"
        label = "Mostly reassuring"
        headline = (
            f"{product} → {event}: current analytics cool the story more than they heat it."
        )
    else:
        tone = "watch"
        label = "Worth a look"
        headline = (
            f"{product} → {event}: not a clear fire, not clearly nothing. Keep on the radar."
        )

    if n < 5 and (sdr or (prr is not None and prr >= 5) or (eb05 is not None and eb05 >= 2)):
        tone = "mixed"
        label = "Mixed — loud but fragile"
        headline = (
            f"{product} → {event}: the dashboard is flashing (SDR / big ratios), but with only "
            f"{n} supporting report(s) this is a fragile early flag — investigate, don't conclude."
        )

    next_step = (
        "Read the supporting posts, check triangulation / FAERS, and wait for more cases "
        "before escalating — unless severity or MaxSPRT / calibration also scream."
        if tone in ("mixed", "watch")
        else (
            "Route to medical review with the SAR / memo; corroborate on FAERS/MAUDE and labels."
            if tone == "concerning"
            else "No urgent action from these numbers alone; re-check if volume or spike grows."
        )
    )

    return {
        "tone": tone,  # concerning | mixed | reassuring | watch
        "label": label,
        "headline": headline,
        "alarms": alarms[:5],
        "coolers": coolers[:5],
        "next_step": next_step,
        "one_liner": f"{label}: {headline}",
    }


def enrich_step_verdict(step: dict[str, str], sig: Any) -> dict[str, str]:
    """Add verdict + takeaway (instant conclusion) onto a tour step."""
    sid = step.get("id") or ""
    n = _n(sig)
    out = dict(step)

    if sid == "remine":
        out["verdict"] = "neutral"
        out["takeaway"] = (
            f"You have {n} AE-flagged post(s) to read. Remine helps find more stories — "
            "it does not make the signal true or false by itself."
        )
    elif sid == "disproportionality":
        prr = _num(_g(sig, "prr"))
        chi2 = _num(_g(sig, "chi_square") if _g(sig, "chi_square") is not None else _g(sig, "chi2"))
        strength = (_g(sig, "strength") or "WEAK").upper()
        sdr = bool(_g(sig, "sdr_flag"))
        prr_ci = _g(sig, "prr_ci") or [None, None]
        lo = _num(prr_ci[0]) if isinstance(prr_ci, (list, tuple)) and len(prr_ci) > 0 else None
        if sdr or strength == "STRONG":
            if n < 8 and prr is not None and prr > 20:
                out["verdict"] = "mixed"
                out["takeaway"] = (
                    f"LOOKS BAD on the surface (SDR / {strength}, PRR≈{_fmt(prr)}) — but with "
                    f"only {n} reports those huge ratios are often statistical fireworks, not "
                    f"proof. Treat as 'investigate soon,' not 'confirmed crisis.'"
                )
            else:
                out["verdict"] = "concerning"
                out["takeaway"] = (
                    f"This is a HOT screening flag ({strength}"
                    f"{', SDR' if sdr else ''}). The pair is reported far more than expected — "
                    "bring a human reviewer in."
                )
        elif strength == "MODERATE":
            out["verdict"] = "watch"
            out["takeaway"] = (
                "Mild-to-moderate excess reporting — worth watching, not an automatic escalate."
            )
        else:
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                "Disproportionality is weak — these numbers do not argue for a strong signal."
            )
        if lo is not None and lo >= 1 and chi2 is not None and chi2 >= 4 and n >= 3:
            out["so_what"] = (
                (out.get("so_what") or "")
                + " Classic SDR-style rule components are met on PRR-CI / χ² / n."
            )
    elif sid == "bayesian":
        eb05 = _num(_g(sig, "eb05"))
        ic025 = _num(_g(sig, "ic025"))
        eb_ok = eb05 is not None and eb05 >= 2
        ic_ok = ic025 is not None and ic025 > 0
        if eb_ok and ic_ok:
            out["verdict"] = "concerning"
            out["takeaway"] = (
                f"Both cautious Bayesian checks agree this is elevated (EB05={_fmt(eb05)}, "
                f"IC025={_fmt(ic025)}). That is harder to shrug off than a raw PRR alone."
            )
        elif eb_ok and not ic_ok:
            out["verdict"] = "mixed"
            out["takeaway"] = (
                f"SPLIT decision: EB05={_fmt(eb05)} clears the usual ≥2 bar (concerning), "
                f"but IC025={_fmt(ic025)} is still ≤0 (not convinced). Do not escalate on "
                "EB05 alone — you need more cases or other pillars."
            )
        elif not eb_ok and ic_ok:
            out["verdict"] = "mixed"
            out["takeaway"] = (
                f"IC025 looks positive ({_fmt(ic025)}) but EB05 ({_fmt(eb05)}) is below 2 — "
                "mixed Bayesian picture."
            )
        else:
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                f"After shrinkage, the signal cools off (EB05={_fmt(eb05)}, IC025={_fmt(ic025)}). "
                "Scary raw ratios are likely small-number noise."
            )
    elif sid == "trend":
        spike = bool(_g(sig, "spike_flag") or _g(sig, "spike"))
        if spike:
            out["verdict"] = "concerning"
            out["takeaway"] = (
                "Talk just spiked — something changed (real harm, news, or bots). "
                "Check Trust + posts today."
            )
        else:
            out["verdict"] = "neutral"
            out["takeaway"] = "No loud spike right now — volume looks steady, not suddenly worse."
    elif sid == "maxsprt":
        crossed = bool(_g(sig, "maxsprt_crossed"))
        mx = _g(sig, "maxsprt") or {}
        if isinstance(mx, dict) and mx.get("crossed"):
            crossed = True
        if crossed:
            out["verdict"] = "concerning"
            out["takeaway"] = (
                "Sequential surveillance STOPPED at the alarm line — this is a formal "
                "'enough evidence to flag' moment on accumulating counts."
            )
        else:
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                "Still under the MaxSPRT stop line — continuous monitoring has not hit alarm yet."
            )
    elif sid == "cox":
        elevated = bool(_g(sig, "hr_elevated"))
        hr = _num(_g(sig, "hr"))
        if elevated or (hr is not None and hr > 1.5):
            out["verdict"] = "concerning"
            out["takeaway"] = (
                f"Timing model says events come faster with this product (HR≈{_fmt(hr)}). "
                "Supportive context — still not causation proof."
            )
        else:
            out["verdict"] = "neutral"
            out["takeaway"] = (
                f"Hazard ratio (~{_fmt(hr)}) is not clearly elevated — timing evidence is soft."
            )
    elif sid == "calibration":
        cal_ok = bool(_g(sig, "calibrated_signal"))
        cal_p = _num(_g(sig, "calibrated_p"))
        e_value = _num(_g(sig, "e_value"))
        if not cal_ok:
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                f"After comparing to the noise floor, this does NOT clear the bar"
                f"{f' (calibrated p≈{cal_p:.3f})' if cal_p is not None else ''}. "
                "The flashy PRR is likely compatible with background chatter — cools the panic."
            )
            if e_value is not None and e_value > 100:
                out["takeaway"] += (
                    f" (Huge E-value {_fmt(e_value)} only means 'IF this were real it would be "
                    "hard to confound away' — it does not override a failed calibration.)"
                )
        else:
            out["verdict"] = "concerning"
            out["takeaway"] = (
                "Survives empirical calibration — less likely to be pure database noise. "
                "Raises priority."
            )
    elif sid == "label_filter":
        label_f = _g(sig, "label_filter") or {}
        tag = ""
        if isinstance(label_f, dict):
            tag = str(label_f.get("tag") or label_f.get("novelty_tier") or "")
        novelty = tag or str(_g(sig, "label_novelty") or "")
        if "NOVEL" in novelty.upper() or novelty.lower() == "novel":
            out["verdict"] = "concerning"
            out["takeaway"] = (
                "Looks NEW vs the label — unexpected events deserve faster eyes than "
                "well-known labeled side effects."
            )
        elif "ESTABLISHED" in novelty.upper() or "in_label" in novelty.lower() or novelty == "in_label":
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                "Already on-label / established — still monitor volume, but novelty urgency is lower."
            )
        else:
            out["verdict"] = "neutral"
            out["takeaway"] = f"Label novelty status: {novelty or 'unknown'}."
    elif sid == "causality":
        who = _g(sig, "who_umc") or ""
        block = _g(sig, "causality_assessment")
        if isinstance(block, dict):
            wb = block.get("who_umc") or {}
            if isinstance(wb, dict) and wb.get("category"):
                who = who or wb.get("category")
        if who in ("Certain", "Probable"):
            out["verdict"] = "concerning"
            out["takeaway"] = (
                f"Causality checklist leans {who} — stories fit a drug/device link better than chance."
            )
        elif who == "Possible":
            out["verdict"] = "watch"
            out["takeaway"] = (
                "Causality is only 'Possible' — plausible but not pinned. Common for thin social text."
            )
        else:
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                f"Causality is {who or 'Unassessable'} — narratives do not strongly blame the product yet."
            )
    elif sid == "triangulation":
        tri = _g(sig, "triangulation") or {}
        tier = (tri.get("urgency_tier") if isinstance(tri, dict) else "") or ""
        n_pass = tri.get("n_pillars_passed") if isinstance(tri, dict) else None
        if "CRITICAL" in tier or "HIGH" in tier:
            out["verdict"] = "concerning"
            out["takeaway"] = (
                f"Multiple evidence lenses agree this is urgent ({tier.replace('_', ' ')}). "
                "Social chatter is not standing alone."
            )
        elif n_pass == 1 or tier in ("EMERGENT_CHATTER", "INSUFFICIENT"):
            out["verdict"] = "watch"
            out["takeaway"] = (
                "Only weak multi-source agreement — social may be ahead of (or isolated from) "
                "regulatory databases. Caution, not conclusion."
            )
        else:
            out["verdict"] = "mixed"
            out["takeaway"] = (
                f"Triangulation tier: {tier or 'n/a'}; pillars passed: {n_pass}. "
                "Use agreement as a confidence dial."
            )
    elif sid == "completeness":
        well = bool(_g(sig, "well_documented"))
        comp = _g(sig, "completeness_detail") or {}
        mean_c = _num(comp.get("mean_completeness") if isinstance(comp, dict) else None)
        if mean_c is None:
            mean_c = _num(_g(sig, "completeness"))
        if mean_c is not None and mean_c < 0.5:
            well = False
        if not well:
            out["verdict"] = "caution"
            out["takeaway"] = (
                f"Poorly documented (mean ≈{_fmt(mean_c)}/1.00, need ≥0.50). "
                "You are deciding with incomplete patient stories — do not escalate on stats alone."
            )
        else:
            out["verdict"] = "reassuring"
            out["takeaway"] = (
                f"Documentation looks usable (≈{_fmt(mean_c)}/1.00) — better ground for review."
            )
    elif sid == "trust":
        label = (_g(sig, "trust_label") or "high").lower()
        if label in ("sybil", "low"):
            out["verdict"] = "caution"
            out["takeaway"] = (
                f"Trust is {label} — the loud stats may be inflated by bots or copy-paste. "
                "Verify authors before escalating."
            )
        elif label == "medium":
            out["verdict"] = "watch"
            out["takeaway"] = "Medium trust — some weirdness in the cohort; read posts carefully."
        else:
            out["verdict"] = "reassuring"
            out["takeaway"] = "Trust looks healthy — less likely a coordinated spam burst."
    elif sid == "four_gate":
        out["verdict"] = "neutral"
        out["takeaway"] = (
            f"{n} post(s) cleared the AE detector gates (product + symptom + negative tone + "
            "not negated). That explains why they count toward this signal."
        )
    elif sid == "disclaimer":
        out["verdict"] = "caution"
        out["takeaway"] = (
            "Prototype / social-listening context — none of these panels equal a confirmed "
            "ADR for regulatory submission or clinical care."
        )
    else:
        # Keep so_what as takeaway if missing
        out.setdefault("verdict", "neutral")
        out.setdefault("takeaway", out.get("so_what") or out.get("what_numbers_say") or "")

    # Prefer takeaway as the human-facing so_what
    if out.get("takeaway"):
        out["so_what"] = out["takeaway"]
    return out


def _fmt(v: float | None, d: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def apply_verdicts(tour: list[dict[str, str]], sig: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    enriched = [enrich_step_verdict(s, sig) for s in tour]
    bottom = build_bottom_line(sig)
    return enriched, bottom
