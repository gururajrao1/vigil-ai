"""Medically strict event acceptance + layman→MedDRA glossary for transparency.

Filter dropdowns and signal rows may only carry Preferred Terms that resolve
through the open MedDRA surrogate (or an explicit synonym/vernacular/embed hit
that lands on a matched PT). Transformer debris like "Calls" / "Thanks" is dropped.
"""
from __future__ import annotations

from typing import Any, Optional

from .meddra import map_term
from .stage1_sanitize import fold_key, sanitize_surface
from .stage2_synonyms import EVENT_SYNONYMS, lookup_event_synonym
from .vernacular import VERNACULAR

# Everyday English that NER tags as "symptoms" but are not clinical events
NONCLINICAL_SURFACE = frozenset({
    "call", "calls", "called", "calling", "thank", "thanks", "thanked",
    "take", "takes", "taken", "taking", "took", "broke", "break", "breaks",
    "myth", "myths", "normal", "desire", "energy", "awake", "appointment",
    "changes", "change", "feelings", "feeling", "healthy", "invalid",
    "extension", "discharge", "discharged", "destroyed", "damage", "damaged",
    "concentrate", "difficulty", "go to work", "free thinking", "thanks",
    "battery problem", "udeny", "drows", "febril", "hunger", "scared",
    "desire", "moods", "mood", "heart", "cancer", "tumor", "tumour",
    "anger", "anger issues", "crying", "tears", "tense", "tired", "sweaty",
    "sweat", "puffy", "shook", "spins", "stiff", "sores", "peeing",
    "bedridden", "breakout", "breakouts", "hangover", "irritated",
    "jerking", "lesions", "flare up", "flare ups", "highs and low",
    "heat waves", "health anxiety", "anti - anxieties", "anti anxieties",
    "feeling better", "fall asleep", "burning and", "device malfunction",
    "loosening / migration of device", "flexion of muscles",
    "extension of muscles", "inflammatory reactions", "internal tremor",
})


def explain_term(surface: str) -> dict[str, Any]:
    """Resolve a layman / raw surface to MedDRA PT with full audit trail."""
    from .text_normalize import run_four_stage_event

    san = sanitize_surface(surface).cleaned
    result = run_four_stage_event(san) if san else None
    if not result:
        return {
            "query": surface,
            "accepted": False,
            "reason": "Not a recognized clinical event (junk, verb, or unmatched layman phrase).",
            "pt": None,
            "soc": None,
            "soc_code": None,
            "stage": None,
            "similarity": None,
            "patient_phrases": [],
        }

    pt = result["pt"]
    # Collect patient phrases that map to this PT
    phrases = patient_phrases_for_pt(pt)
    return {
        "query": surface,
        "accepted": True,
        "reason": "Mapped to MedDRA-style Preferred Term.",
        "pt": pt,
        "soc": result.get("soc"),
        "soc_code": result.get("soc_code"),
        "stage": result.get("stage"),
        "similarity": result.get("similarity"),
        "patient_phrases": phrases,
        "disclaimer": (
            "Open MedDRA surrogate coding — not a licensed MedDRA dictionary. "
            "Prototype; not for clinical use."
        ),
    }


def patient_phrases_for_pt(pt: str) -> list[str]:
    """All vernacular + synonym surfaces that resolve to this Preferred Term."""
    target = (pt or "").strip().lower()
    if not target:
        return []
    phrases: set[str] = set()
    # Vernacular idioms
    for phrase, canon in VERNACULAR.items():
        md = map_term(canon)
        if md.get("matched") and md["pt"].lower() == target:
            phrases.add(phrase)
    # Explicit event synonyms
    for fold, canon in EVENT_SYNONYMS.items():
        md = map_term(canon)
        if md.get("matched") and md["pt"].lower() == target:
            # reconstruct a readable form from fold is hard; use canon + fold lower
            phrases.add(canon)
    # Direct PT map surfaces
    from .meddra import _PT_MAP

    for surface, (pref, _) in _PT_MAP.items():
        if pref.lower() == target:
            phrases.add(surface)
    return sorted(phrases, key=lambda x: (len(x), x.lower()))


def build_glossary() -> dict[str, Any]:
    """Full layman → PT glossary for the Evidence UI (browseable, no typing required)."""
    from .meddra import _PT_MAP

    rows: list[dict] = []
    seen: set[str] = set()

    def _add(phrase: str, source: str) -> None:
        key = fold_key(phrase)
        if not key or key in seen:
            return
        info = explain_term(phrase)
        if not info["accepted"]:
            return
        seen.add(key)
        rows.append({
            "patient_phrase": phrase,
            "source": source,
            "pt": info["pt"],
            "soc": info["soc"],
            "soc_code": info["soc_code"],
            "stage": info["stage"],
        })

    for phrase in sorted(VERNACULAR.keys(), key=len, reverse=True):
        _add(phrase, "vernacular")
    for _fold, canon in sorted(EVENT_SYNONYMS.items()):
        _add(canon, "synonym")
    for surface in sorted(_PT_MAP.keys()):
        _add(surface, "meddra_surface")

    by_pt: dict[str, dict] = {}
    for row in rows:
        pt = row["pt"]
        bucket = by_pt.setdefault(pt, {
            "pt": pt,
            "soc": row["soc"],
            "soc_code": row["soc_code"],
            "patient_phrases": [],
        })
        if row["patient_phrase"] not in bucket["patient_phrases"]:
            bucket["patient_phrases"].append(row["patient_phrase"])

    grouped = sorted(by_pt.values(), key=lambda r: (r["pt"] or "").lower())
    for g in grouped:
        g["patient_phrases"] = sorted(set(g["patient_phrases"]), key=str.lower)

    # Flat dropdown options: every patient phrase → PT (primary UX)
    phrase_options = sorted(
        (
            {
                "label": f"{r['patient_phrase']}  →  {r['pt']}",
                "patient_phrase": r["patient_phrase"],
                "pt": r["pt"],
                "soc": r["soc"],
                "soc_code": r["soc_code"],
                "source": r["source"],
            }
            for r in rows
        ),
        key=lambda r: r["patient_phrase"].lower(),
    )

    return {
        "count": len(grouped),
        "phrase_count": len(phrase_options),
        "terms": grouped,
        "phrases": phrase_options,
        "purpose": (
            "Reference dictionary for safety scientists: shows how patient-voice "
            "wording is coded to MedDRA-style Preferred Terms used in KG filters, "
            "signals, and disproportionality. It does not create signals — it "
            "explains the coding already applied at ingest."
        ),
        "disclaimer": (
            "Patient-voice phrases are mapped to an open MedDRA-style Preferred Term "
            "and System Organ Class. Individual comorbidities in consumer text remain "
            "unverified. Not for clinical use."
        ),
    }


def is_nonclinical_surface(value: str) -> bool:
    low = sanitize_surface(value).cleaned.lower()
    return low in NONCLINICAL_SURFACE
