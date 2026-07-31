"""Remine lab — always-on competition-bias demos with before/after deltas.

Finds product–event pairs that share competitors in the corpus, runs remine,
and returns actionable cards (so analysts never hit a dead disabled button).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Signal
from .corpus import build_ae_reports
from .masking import analyze_masking, remine_unmasked


def _lookup_signal(
    db: Session, drug: str, event: str, project_id: Optional[int]
) -> Optional[Signal]:
    q = db.query(Signal).filter(Signal.drug.ilike(drug))
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    for cand in q.limit(40).all():
        ev_l = (event or "").lower()
        if (cand.symptom or "").lower() == ev_l or (cand.meddra_pt or "").lower() == ev_l:
            return cand
        if ev_l and (
            ev_l in (cand.symptom or "").lower()
            or ev_l in (cand.meddra_pt or "").lower()
            or (cand.symptom or "").lower() in ev_l
        ):
            return cand
    return None


def build_remine_lab(
    db: Session,
    project_id: Optional[int] = None,
    *,
    limit: int = 8,
) -> dict:
    corpus = build_ae_reports(db, project_id=project_id)
    reports = corpus["reports"]
    posts = corpus["posts"]

    by_event: Dict[str, Counter] = defaultdict(Counter)
    for d, e in reports:
        by_event[e][(d or "").lower()] += 1

    cards: List[dict] = []
    seen = set()

    # Rank: events with a clear dominant + a secondary product
    ranked_events = []
    for ev, counts in by_event.items():
        if len(counts) < 2:
            continue
        top = counts.most_common()
        dominant, dom_n = top[0]
        for other, n in top[1:5]:
            if n < 1:
                continue
            # Prefer cases where secondary is smaller (masking scenario)
            score = dom_n * 10 + n
            ranked_events.append((score, other, dominant, ev, n, dom_n))
    ranked_events.sort(reverse=True)

    for _score, target, masker, ev, t_n, m_n in ranked_events:
        key = (target, ev.lower())
        if key in seen:
            continue
        seen.add(key)

        analysis = analyze_masking(reports, target, ev)
        if not analysis.get("can_remine"):
            continue
        exclude = analysis.get("suggested_exclude") or [masker]
        remine = remine_unmasked(
            posts, target, ev, exclude, full_reports=reports
        )
        sig = _lookup_signal(db, target, ev, project_id)
        before = (remine.get("baseline") or {}).get("prr")
        after = (remine.get("unmasked") or {}).get("prr") if remine.get("unmasked") else None
        cards.append({
            "drug": target,
            "event": ev,
            "signal_id": sig.id if sig else None,
            "maskers": exclude,
            "competitor_counts": {"target": t_n, "top_masker": m_n, "masker": masker},
            "masking_risk": analysis.get("masking_risk"),
            "before_prr": before,
            "after_prr": after,
            "delta_prr": (remine.get("delta") or {}).get("prr_delta"),
            "signal_strengthened": remine.get("signal_strengthened"),
            "interpretation": remine.get("interpretation"),
            "verdict": analysis.get("verdict"),
            "action": (
                f"Open the signal and remine without {', '.join(exclude)} — "
                + (
                    "PRR rose after unmasking (competition bias likely)."
                    if remine.get("signal_strengthened")
                    else "compare before/after PRR on the signal page."
                )
            ),
        })
        if len(cards) >= limit:
            break

    # Prefer strengthened examples first
    cards.sort(
        key=lambda c: (
            1 if c.get("signal_strengthened") else 0,
            abs(c.get("delta_prr") or 0),
        ),
        reverse=True,
    )

    return {
        "cards": cards,
        "n_cards": len(cards),
        "n_reports": len(reports),
        "needs_demo_seed": len(cards) < 2,
        "headline": (
            f"{len(cards)} remine-ready competition-bias case(s) in this workspace."
            if cards
            else "No shared events with competitors yet — load the PV demo pack."
        ),
        "how_to_use": (
            "Pick a card → open the signal → Remine runs with competitors pre-selected. "
            "If PRR rises after removing the dominant product, competition bias may have "
            "been suppressing the signal."
        ),
        "disclaimer": (
            "Sensitivity analysis on the VigilAI corpus — not a regulatory decision. "
            "Prototype; not for clinical use."
        ),
    }
