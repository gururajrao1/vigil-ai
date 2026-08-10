"""Agentic causality assessment — WHO-UMC + Naranjo (GVP Module 2).

Offline-first. Wraps the deterministic WHO-UMC scorer and adds a 10-question
Naranjo algorithm plus structured dechallenge/rechallenge extraction.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..analytics.causality import (
    _CONFOUNDER,
    _DECHALLENGE,
    _RECHALLENGE,
    _TEMPORAL,
    assess_causality,
    grade_severity,
)

_DISCLAIMER = (
    "Prototype WHO-UMC + Naranjo automation over social/ICSR narratives. "
    "AI-assisted draft requiring QPPV/Medical Reviewer validation. "
    "Not for clinical decision-making or regulatory submission."
)

# Extra Naranjo lexicons
_PLACEBO = ["placebo", "dummy pill", "sugar pill"]
_DOSE_DEPENDENT = [
    "higher dose", "increased dose", "dose increase", "more mg",
    "doubled the dose", "up-titrated", "after increasing",
]
_LEVELS = [
    "blood level", "serum level", "plasma concentration", "toxic level",
    "drug level", "above therapeutic",
]
_ALTERNATIVE = [
    "could be", "might be", "also caused by", "due to infection",
    "viral", "underlying disease", "disease progression",
]
_NEGATIVE_DECHALLENGE = [
    "continued after stopping", "did not resolve", "still had",
    "persisted after discontinu", "didn't go away when i stopped",
]
_PREVIOUS_REPORTS = [
    "known side effect", "listed on the label", "common with",
    "warned about", "black box", "doctor said it can cause",
]


def _has_any(text: str, phrases: List[str]) -> bool:
    t = text or ""
    return any(p in t for p in phrases)


def _find_spans(text: str, phrases: List[str]) -> List[dict]:
    t = text or ""
    tl = t.lower()
    out = []
    for p in phrases:
        idx = tl.find(p)
        if idx >= 0:
            out.append({"phrase": p, "start": idx, "end": idx + len(p), "surface": t[idx: idx + len(p)]})
    return out


def extract_dechallenge_rechallenge(text: str) -> dict:
    """Structured de/rechallenge tags from narrative cues (ConText-style offline)."""
    raw = text or ""
    tl = raw.lower()
    pos_de = _find_spans(tl, _DECHALLENGE)
    neg_de = _find_spans(tl, _NEGATIVE_DECHALLENGE)
    pos_re = _find_spans(tl, _RECHALLENGE)
    temporal = _find_spans(tl, _TEMPORAL)
    return {
        "positive_dechallenge": bool(pos_de) and not bool(neg_de),
        "negative_dechallenge": bool(neg_de),
        "positive_rechallenge": bool(pos_re),
        "temporal_relationship": bool(temporal),
        "spans": {
            "dechallenge_positive": pos_de[:5],
            "dechallenge_negative": neg_de[:5],
            "rechallenge_positive": pos_re[:5],
            "temporal": temporal[:5],
        },
    }


def naranjo_score(
    text: str,
    *,
    product: str = "",
    event: str = "",
    fda_known: bool = False,
) -> dict:
    """10-item Naranjo ADR probability scale (−4 … +12).

    Yes / No / Do not know mapping uses narrative cues; unanswered items score 0
    (Do not know) — honest under sparse social text.
    """
    tl = (text or "").lower()
    items: List[dict] = []

    def _q(qid: int, question: str, yes: int, no: int, answered: Optional[bool], note: str = "") -> None:
        if answered is True:
            pts, ans = yes, "yes"
        elif answered is False:
            pts, ans = no, "no"
        else:
            pts, ans = 0, "do_not_know"
        items.append({
            "id": qid,
            "question": question,
            "answer": ans,
            "points": pts,
            "note": note,
        })

    # 1. Previous conclusive reports?
    prev = fda_known or _has_any(tl, _PREVIOUS_REPORTS)
    _q(1, "Are there previous conclusive reports on this reaction?", 1, 0, True if not (fda_known or prev) else prev)

    # 2. Adverse event appear after suspected drug?
    temp = _has_any(tl, _TEMPORAL)
    _q(2, "Did the adverse event appear after the suspected drug was administered?", 2, -1, True if temp else None)

    # 3. Improve on discontinuation (dechallenge)?
    pos_de = _has_any(tl, _DECHALLENGE)
    neg_de = _has_any(tl, _NEGATIVE_DECHALLENGE)
    de_ans: Optional[bool]
    if pos_de and not neg_de:
        de_ans = True
    elif neg_de:
        de_ans = False
    else:
        de_ans = None
    _q(3, "Did the adverse reaction improve when the drug was discontinued?", 1, 0, de_ans)

    # 4. Reappear on rechallenge?
    re_ans = True if _has_any(tl, _RECHALLENGE) else None
    _q(4, "Did the adverse reaction reappear when the drug was readministered?", 2, -1, re_ans)

    # 5. Alternative causes?
    alt = _has_any(tl, _ALTERNATIVE) or _has_any(tl, _CONFOUNDER)
    # Yes alternative → −1; No alternative → +2; unknown → 0
    _q(5, "Are there alternative causes that could on their own have caused the reaction?", -1, 2, True if alt else None)

    # 6. Reappear with placebo?
    plac = _has_any(tl, _PLACEBO)
    _q(6, "Did the reaction reappear when a placebo was given?", -1, 1, False if plac else None)

    # 7. Drug detected in blood (toxic)?
    levels = _has_any(tl, _LEVELS)
    _q(7, "Was the drug detected in blood (or other fluids) in toxic concentrations?", 1, 0, True if levels else None)

    # 8. Dose-dependent severity?
    dose = _has_any(tl, _DOSE_DEPENDENT)
    _q(8, "Was the reaction more severe when the dose was increased, or less severe when decreased?", 1, 0, True if dose else None)

    # 9. Similar reaction to same/similar drug previously?
    similar = bool(re.search(r"\b(same reaction|happened before|last time i took)\b", tl))
    _q(9, "Did the patient have a similar reaction to the same or similar drugs in any previous exposure?", 1, 0, True if similar else None)

    # 10. Confirmed by objective evidence?
    objective = bool(re.search(r"\b(lab|biopsy|ecg|mri|confirmed by|diagnosed)\b", tl))
    _q(10, "Was the adverse event confirmed by any objective evidence?", 1, 0, True if objective else None)

    total = int(sum(i["points"] for i in items))
    if total >= 9:
        category = "Definite"
    elif total >= 5:
        category = "Probable"
    elif total >= 1:
        category = "Possible"
    else:
        category = "Doubtful"

    return {
        "algorithm": "naranjo",
        "score": total,
        "score_range": [-4, 12],
        "category": category,
        "items": items,
        "product": (product or "").lower(),
        "event": (event or "").lower(),
    }


def evaluate_narrative_causality(
    text: str,
    *,
    product: str = "",
    event: str = "",
    fda_known: bool = False,
    product_type: str = "drug",
    use_optional_bionlp: bool = False,
) -> dict:
    """Combined WHO-UMC + Naranjo + de/rechallenge extraction."""
    # Optional BioNLP reserved — lexicon path is default (fast, offline).
    _ = use_optional_bionlp

    who = assess_causality(
        text or "",
        product,
        event,
        fda_known=fda_known,
        product_type=product_type,
    )
    severity = grade_severity(event, who.get("category") or "Unassessable")
    naranjo = naranjo_score(text or "", product=product, event=event, fda_known=fda_known)
    tags = extract_dechallenge_rechallenge(text or "")

    return {
        "product": (product or "").lower(),
        "event": (event or "").lower(),
        "who_umc": who,
        "severity": severity,
        "naranjo": naranjo,
        "dechallenge_rechallenge": tags,
        "pipeline": "causality_engine_v1",
        "offline": True,
        "disclaimer": _DISCLAIMER,
    }
