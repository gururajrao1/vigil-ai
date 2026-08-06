"""Deterministic plain-English signal briefing for non-technical stakeholders.

Builds a so-what summary from existing signal fields — no LLM required.
Offline-first; pairs every metric mention with a gloss.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


_DISCLAIMER = (
    "Prototype briefing for orientation only — not a clinical decision aid. "
    "openFDA is US FAERS/MAUDE; MedDRA coding is an open surrogate."
)


def _worry_level(sig: dict) -> Dict[str, str]:
    strength = (sig.get("strength") or "WEAK").upper()
    sdr = bool(sig.get("sdr_flag"))
    spike = bool(sig.get("spike_flag"))
    severity = (sig.get("severity") or "").lower()
    critical = severity in ("critical", "high", "life-threatening", "death")

    if (sdr and strength == "STRONG") or (spike and critical) or (
        strength == "STRONG" and critical
    ):
        return {
            "level": "red",
            "label": "Needs attention",
            "phrase": "This stands out strongly and should be reviewed soon.",
        }
    if sdr or strength in ("STRONG", "MODERATE") or spike or critical:
        return {
            "level": "amber",
            "label": "Worth a closer look",
            "phrase": "There are enough clues to dig in, but it is not an automatic alarm.",
        }
    return {
        "level": "green",
        "label": "Lower urgency",
        "phrase": "Signal is weak or sparse — monitor, but other cases may matter more first.",
    }


def _why_bullets(sig: dict) -> List[str]:
    bullets: List[str] = []
    n = sig.get("post_count") or sig.get("a") or 0
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if n >= 10:
        bullets.append(f"There are {n} supporting reports in our listening corpus.")
    elif n >= 3:
        bullets.append(f"We have {n} supporting reports — enough to start a review.")
    elif n > 0:
        bullets.append(f"Only {n} supporting report(s) so far — treat as early / thin evidence.")

    if sig.get("sdr_flag"):
        bullets.append(
            "Statistical checks flag this product-event pair as unusually common "
            "(SDR - Signal of Disproportionate Reporting)."
        )
    strength = (sig.get("strength") or "").upper()
    if strength == "STRONG":
        bullets.append("Strength tier is STRONG (high reporting rate vs the rest of the corpus).")
    elif strength == "MODERATE":
        bullets.append("Strength tier is MODERATE — elevated, but not the top tier.")

    if sig.get("spike_flag"):
        bullets.append("Reporting looks like it is spiking recently compared with its own history.")

    fda = sig.get("fda_evidence") or {}
    if fda.get("available") and (fda.get("report_count") or 0) > 0:
        src = "MAUDE" if "maude" in str(fda.get("source") or "").lower() else "FAERS"
        bullets.append(
            f"Similar reports appear in US FDA {src} "
            f"({int(fda.get('report_count') or 0):,} openFDA hits)."
        )

    who = sig.get("who_umc") or ""
    if who and who.lower() not in ("unassessable", "unlikely", ""):
        bullets.append(f"Causality cues lean {who} on the WHO-UMC scale (text-pattern based).")

    if not bullets:
        bullets.append("Limited structured evidence yet — open supporting posts to read the raw accounts.")
    return bullets[:4]


def _one_sentence(sig: dict) -> str:
    drug = (sig.get("drug") or "this product").strip()
    event = (
        (sig.get("meddra") or {}).get("pt")
        or sig.get("meddra_pt")
        or sig.get("symptom")
        or "this adverse event"
    )
    ptype = (sig.get("product_type") or "drug").lower()
    kind = "device" if ptype == "device" else ("vaccine" if ptype == "vaccine" else "medicine")
    n = sig.get("post_count") or 0
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0

    if sig.get("sdr_flag") or (sig.get("strength") or "").upper() == "STRONG":
        return (
            f"People are reporting {event} with the {kind} {drug} "
            f"more often than we would expect by chance"
            + (f" ({n} reports in our corpus)." if n else ".")
        )
    if (sig.get("strength") or "").upper() == "MODERATE":
        return (
            f"There is a moderate signal that {event} may be linked with the {kind} {drug} "
            f"in patient and regulatory chatter"
            + (f" ({n} reports)." if n else ".")
        )
    return (
        f"We are tracking reports of {event} with the {kind} {drug}, "
        f"but the statistical signal is still weak or based on few cases"
        + (f" ({n} reports)." if n else ".")
    )


def _next_steps(sig: dict) -> List[Dict[str, str]]:
    steps = [
        {"id": "posts", "label": "Read patient / case reports", "action": "scroll_posts"},
        {"id": "workflow", "label": "Assign in Workflow", "action": "scroll_workflow"},
        {"id": "sar", "label": "Export assessment (SAR)", "action": "export_sar"},
    ]
    # Remine only when competition bias is plausible — frontend also gates on masking
    steps.append({"id": "remine", "label": "Check competition bias (Remine)", "action": "scroll_remine"})
    steps.append({
        "id": "risk",
        "label": "Who might be highest risk?",
        "action": "open_risk_populations",
        "href": f"/lenses?tab=risk&product_id={sig.get('drug') or ''}&target_ae_pt={sig.get('symptom') or ''}",
    })
    return steps


def _glossary(sig: dict) -> List[Dict[str, str]]:
    items = [
        {
            "term": "PRR",
            "plain": "How many times more often this side effect is reported with this product vs everything else.",
        },
        {
            "term": "EB05 / IC025",
            "plain": "Cautious versions of the stats that shrink small-sample noise — if these stay high, the signal is more believable.",
        },
        {
            "term": "SDR",
            "plain": "A composite flag that the reporting pattern looks disproportionate enough to triage.",
        },
    ]
    if sig.get("spike_flag"):
        items.append({
            "term": "Spike",
            "plain": "Recent days have unusually many reports compared with this pair’s own history.",
        })
    return items


def build_signal_briefing(sig: dict) -> Dict[str, Any]:
    """Return a briefing dict for Signal Detail (non-technical first view)."""
    if not sig:
        return {
            "headline": "No signal loaded.",
            "worry": {"level": "green", "label": "Unknown", "phrase": ""},
            "why": [],
            "glossary": [],
            "next_steps": [],
            "narrative_plain": "",
            "disclaimer": _DISCLAIMER,
        }

    worry = _worry_level(sig)
    narrative = (sig.get("narrative") or "").strip()
    # Prefer short grounded narrative when present; else one-sentence template
    if narrative and len(narrative) < 420:
        narrative_plain = narrative
    else:
        narrative_plain = _one_sentence(sig)
        if narrative and len(narrative) >= 420:
            narrative_plain = narrative[:380].rsplit(" ", 1)[0] + "…"

    prr = sig.get("prr")
    prr_plain = None
    if prr is not None:
        try:
            prr_f = float(prr)
            prr_plain = (
                f"About {prr_f:.1f}× more often than the background rate in our corpus."
                if prr_f >= 1.05
                else "Not clearly elevated vs the rest of the corpus."
            )
        except (TypeError, ValueError):
            prr_plain = None

    return {
        "headline": _one_sentence(sig),
        "narrative_plain": narrative_plain,
        "worry": worry,
        "why": _why_bullets(sig),
        "prr_plain": prr_plain,
        "glossary": _glossary(sig),
        "next_steps": _next_steps(sig),
        "product": sig.get("drug"),
        "event": (sig.get("meddra") or {}).get("pt") or sig.get("symptom"),
        "disclaimer": _DISCLAIMER,
    }
