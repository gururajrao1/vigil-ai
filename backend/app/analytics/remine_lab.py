"""Remine lab — corpus-wide competition-bias screening with honest effect decomposition.

Screens *every* remine-eligible (product, event) pair in the workspace corpus. A
pair is eligible when two or more distinct products report the same event, so one
product's reporting mass can suppress another's disproportionality
(Pariente 2007; Maignen 2014; ENCePP Ch.11).

Why a raw before/after PRR comparison is not enough
---------------------------------------------------
Removing a masker shrinks the *comparator* arm of the 2x2 table, so for
PRR = (a/(a+b)) / (c/(c+d)) the PRR rises for essentially every product left
reporting that event. That rise is the masking effect, but it is shared: it is
the *same multiplicative factor* for every product on the event and so ranks
nothing. Flagging all of them as "signal strengthened" cries wolf on the whole
corpus.

Each card therefore decomposes the masking ratio exactly:

    MR = PRR_after / PRR_before = coreporting_term x comparator_term

    coreporting_term = (a/(a+b))_after  / (a/(a+b))_before   <- pair-specific
    comparator_term  = (c/(c+d))_before / (c/(c+d))_after    <- shared by event

The comparator term is the classical masking effect (a dominant product inflated
the background rate for this event). The co-reporting term is pair-specific and
moves only when the target's own cases were reported alongside the masker, which
points at confounding rather than masking.

What is actionable per pair is whether unmasking pushes it *across the
signalling threshold* — that is the one outcome that changes a conclusion.

Exclusion is applied at *case* level (drop whole reports that mention a masker),
which is how spontaneous reporting systems unmask; row-level exclusion leaves the
target's own a/(a+b) untouched and so cannot surface co-reporting at all.

Performance: baseline DMA is computed once and residual DMA is memoised per
exclusion-set, so screening N pairs costs ~(1 + distinct masker sets) passes
instead of 3N. Results are cached against a corpus fingerprint.
"""
from __future__ import annotations

from collections import Counter, OrderedDict, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Signal
from .corpus import build_ae_reports, reports_from_posts_excluding_maskers
from .disproportionality import compute_signals

# Ceiling on pairs evaluated per rebuild — protects free-tier CPU on big corpora.
MAX_EVAL_PAIRS = 600
# Maximum competitors ranked per event (mirrors analyze_masking top_n).
MAX_MASKERS = 10
# Maximum competitors auto-selected for exclusion.
MAX_EXCLUDE = 3
# A competitor needs at least this many reports of the event to be a credible
# masker — a single report cannot suppress anything.
MIN_MASKER_COUNT = 2
# Effect thresholds (same 15% band remine_unmasked uses).
UP, DOWN = 1.15, 0.85

_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_MAX = 3

DmaIndex = Dict[Tuple[str, str], dict]


class _CorpusStats:
    """Counters needed for the 2x2 decomposition on one report list."""

    __slots__ = ("n", "by_drug", "by_event", "by_pair")

    def __init__(self, reports: List[Tuple[str, str]]):
        self.n = len(reports)
        self.by_drug = Counter(d.lower() for d, _ in reports)
        self.by_event = Counter(e for _, e in reports)
        self.by_pair = Counter((d.lower(), e) for d, e in reports)

    def target_rate(self, drug: str, event: str) -> Optional[float]:
        """a / (a + b) — the target's own share of reports that are this event."""
        n_drug = self.by_drug.get(drug, 0)
        if not n_drug:
            return None
        return self.by_pair.get((drug, event), 0) / n_drug

    def comparator_rate(self, drug: str, event: str) -> Optional[float]:
        """c / (c + d) — everyone else's share of reports that are this event."""
        a = self.by_pair.get((drug, event), 0)
        denom = self.n - self.by_drug.get(drug, 0)
        if denom <= 0:
            return None
        return (self.by_event.get(event, 0) - a) / denom


# --------------------------------------------------------------------------- #
# Masker ranking
# --------------------------------------------------------------------------- #
def _rank_maskers(
    by_drug: Counter, target: str, event_total: int
) -> Tuple[List[dict], int]:
    target_count = int(by_drug.get(target, 0))
    maskers: List[dict] = []
    for other, cnt in by_drug.most_common():
        if other == target:
            continue
        share = cnt / event_total if event_total else 0.0
        pressure = cnt / max(target_count, 1)
        credible = cnt >= MIN_MASKER_COUNT
        maskers.append({
            "drug": other,
            "count": int(cnt),
            "event_share": round(share, 4),
            "vs_target_ratio": round(pressure, 3),
            "likely_masker": credible and (share >= 0.10 or cnt > target_count),
        })
        if len(maskers) >= MAX_MASKERS:
            break
    return maskers, target_count


def _masking_risk(maskers: List[dict], target_share: float) -> str:
    if not maskers:
        return "none"
    top_share = maskers[0]["event_share"]
    if top_share >= 0.35 and target_share < 0.40:
        return "high"
    if top_share >= 0.15 or any(m["likely_masker"] for m in maskers):
        return "moderate"
    return "low"


def _evidence_tier(target_count: int) -> str:
    """Disproportionality needs >=3 cases (Evans criterion) to be evaluable."""
    if target_count >= 3:
        return "evaluable"
    if target_count == 2:
        return "provisional"
    return "exploratory"


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def _dma_index(reports: List[Tuple[str, str]]) -> DmaIndex:
    return {
        (s["drug"].lower(), s["symptom"].lower()): s
        for s in compute_signals(reports)
    }


def _signal_index(
    db: Session, project_id: Optional[int]
) -> Dict[Tuple[str, str], Tuple[int, str]]:
    """Batch-resolve (product, event) -> (signal_id, product_type) in one query."""
    q = db.query(
        Signal.id, Signal.drug, Signal.symptom, Signal.meddra_pt, Signal.product_type
    )
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    idx: Dict[Tuple[str, str], Tuple[int, str]] = {}
    for sid, drug, symptom, pt, ptype in q.all():
        d = (drug or "").lower()
        if not d:
            continue
        for ev in {(symptom or "").lower(), (pt or "").lower()}:
            if ev:
                idx.setdefault((d, ev), (sid, ptype or "drug"))
    return idx


# --------------------------------------------------------------------------- #
# Full corpus screen
# --------------------------------------------------------------------------- #
def effective_project_id(db: Session, project_id: Optional[int]) -> Optional[int]:
    """Resolve the corpus scope Signal Detail will remine in.

    ``/signals/{id}/unmask`` falls back to the signal's own project when no
    active scope header is present. Screening a pooled multi-project corpus here
    would make the lab and the signal page disagree on the same pair, so mirror
    that fallback using the dominant project in the signals table.
    """
    if project_id is not None:
        return project_id
    from sqlalchemy import func

    row = (
        db.query(Signal.project_id, func.count(Signal.id).label("n"))
        .filter(Signal.project_id.isnot(None))
        .group_by(Signal.project_id)
        .order_by(func.count(Signal.id).desc())
        .first()
    )
    return row[0] if row else None


def _screen_corpus(db: Session, project_id: Optional[int]) -> dict:
    project_id = effective_project_id(db, project_id)
    corpus = build_ae_reports(db, project_id=project_id)
    reports: List[Tuple[str, str]] = corpus["reports"]
    posts: List[dict] = corpus["posts"]

    by_event: Dict[str, Counter] = defaultdict(Counter)
    for d, e in reports:
        by_event[e][(d or "").lower()] += 1
    shared_events = {ev: c for ev, c in by_event.items() if len(c) >= 2}

    # --- enumerate every eligible pair, ranked so the most informative survive
    candidates: List[Tuple[float, str, str, List[dict], int, int]] = []
    for ev, counts in shared_events.items():
        event_total = sum(counts.values())
        for target in counts:
            maskers, target_count = _rank_maskers(counts, target, event_total)
            if not maskers:
                continue
            credible = [m for m in maskers if m["likely_masker"]]
            priority = (
                (2000 if credible else 0)
                + target_count * 50
                + maskers[0]["count"] * 5
                + event_total
            )
            candidates.append(
                (priority, target, ev, maskers, target_count, event_total)
            )
    total_eligible = len(candidates)
    candidates.sort(key=lambda c: c[0], reverse=True)
    candidates = candidates[:MAX_EVAL_PAIRS]

    base_stats = _CorpusStats(reports)
    baseline_idx = _dma_index(reports) if reports else {}
    sig_idx = _signal_index(db, project_id)
    resid_cache: Dict[frozenset, Tuple[DmaIndex, _CorpusStats]] = {}

    def residual(excl: frozenset) -> Tuple[DmaIndex, _CorpusStats]:
        hit = resid_cache.get(excl)
        if hit is None:
            # Case-level unmasking: drop whole reports mentioning a masker.
            filtered = reports_from_posts_excluding_maskers(posts, set(excl))
            hit = (_dma_index(filtered) if filtered else {}, _CorpusStats(filtered))
            resid_cache[excl] = hit
        return hit

    cards: List[dict] = []
    for _prio, target, ev, maskers, target_count, event_total in candidates:
        exclude = [m["drug"] for m in maskers if m["likely_masker"]][:MAX_EXCLUDE]
        credible_masker = bool(exclude)
        if not exclude:
            exclude = [maskers[0]["drug"]]
        excl_key = frozenset(d.lower() for d in exclude)

        before = baseline_idx.get((target, ev.lower()))
        after_idx, after_stats = residual(excl_key)
        after = after_idx.get((target, ev.lower()))

        b_prr = (before or {}).get("prr")
        a_prr = (after or {}).get("prr")
        was_sdr = bool((before or {}).get("sdr_flag"))
        now_sdr = bool((after or {}).get("sdr_flag"))

        # --- exact decomposition of the masking ratio
        mr = coreport = comparator = None
        t_before = base_stats.target_rate(target, ev)
        t_after = after_stats.target_rate(target, ev)
        c_before = base_stats.comparator_rate(target, ev)
        c_after = after_stats.comparator_rate(target, ev)
        if t_before and t_after is not None:
            coreport = t_after / t_before
        if c_before and c_after:
            comparator = c_before / c_after
        if b_prr and a_prr:
            mr = a_prr / b_prr

        names = ", ".join(sorted(exclude))
        if after is None or not t_after:
            outcome = "vanished"
            interpretation = (
                f"Every {target} report of this event is co-reported with {names}. "
                "The pair disappears from the residual corpus, so the association is "
                "carried entirely by shared cases — review for confounding rather "
                "than masking."
            )
        elif now_sdr and not was_sdr:
            outcome = "unmasked"
            interpretation = (
                f"Crosses the signalling threshold once {names} is removed — this "
                f"pair was genuinely masked. {target} was below the signalling cut-off "
                "only because a competitor inflated the background rate for this "
                "event. Escalate for review."
            )
        elif was_sdr and not now_sdr:
            outcome = "attenuated"
            interpretation = (
                f"Drops below the signalling threshold once {names} is removed — the "
                "disproportionality was sustained by shared reporting patterns rather "
                "than by this pair on its own."
            )
        elif coreport is not None and not (DOWN <= coreport <= UP):
            outcome = "co_reported"
            direction = "rises" if coreport > 1 else "falls"
            interpretation = (
                f"{target}'s own reporting rate for this event {direction} "
                f"{coreport:.2f}x once {names} cases are removed, so its cases overlap "
                "the competitor's. That points at confounding or co-reporting rather "
                "than pure masking — review the shared cases."
            )
        elif mr is not None and mr <= DOWN:
            outcome = "attenuated"
            interpretation = (
                f"PRR falls {mr:.2f}x after removing {names} — the association was "
                "partly inflated by shared reporting patterns."
            )
        elif mr is not None and mr >= UP:
            outcome = "amplified"
            shared = (
                f"the same {comparator:.2f}x comparator factor"
                if comparator else "the same comparator factor"
            )
            interpretation = (
                f"PRR rises {mr:.2f}x after removing {names}, but every product "
                f"reporting this event gains {shared} and this pair still does not "
                "cross the signalling threshold. Expected masking arithmetic — "
                "monitor, no action yet."
            )
        else:
            outcome = "stable"
            interpretation = (
                f"Metrics stable after removing {names}. Competition bias does not "
                "appear to drive this signal."
            )

        strengthened = outcome in ("unmasked", "co_reported")
        target_share = target_count / event_total if event_total else 0.0
        risk = _masking_risk(maskers, target_share)
        sid, ptype = sig_idx.get((target, ev.lower()), (None, "drug"))
        tier = _evidence_tier(target_count)

        cards.append({
            "drug": target,
            "event": ev,
            "signal_id": sid,
            "product_type": ptype,
            "maskers": exclude,
            "masker_candidates": maskers[:5],
            "credible_masker": credible_masker,
            "masking_risk": risk,
            "evidence_tier": tier,
            "event_total": event_total,
            "target_count": target_count,
            "target_share": round(target_share, 4),
            "top_masker": maskers[0]["drug"],
            "top_masker_count": maskers[0]["count"],
            "reports_before": base_stats.n,
            "reports_after": after_stats.n,
            "before_prr": b_prr,
            "after_prr": a_prr,
            "delta_prr": round(a_prr - b_prr, 3) if (b_prr and a_prr) else None,
            "before_ic025": (before or {}).get("ic025"),
            "after_ic025": (after or {}).get("ic025"),
            "before_strength": (before or {}).get("strength"),
            "after_strength": (after or {}).get("strength"),
            "before_sdr": was_sdr,
            "after_sdr": now_sdr,
            "masking_ratio": round(mr, 3) if mr else None,
            "coreporting_ratio": round(coreport, 3) if coreport else None,
            "comparator_ratio": round(comparator, 3) if comparator else None,
            "signal_strengthened": strengthened,
            "signal_attenuated": outcome == "attenuated",
            "outcome": outcome,
            "interpretation": interpretation,
            "action": (
                f"Remine {target} without {names}"
                if strengthened or outcome == "vanished"
                else f"Screened against {names} — no threshold change"
            ),
        })

    return {
        "cards": cards,
        "products": sorted({c["drug"] for c in cards}),
        "events": sorted({c["event"] for c in cards}),
        "total_eligible": total_eligible,
        "n_reports": len(reports),
        "n_ae_posts": len(posts),
        "n_events": len(by_event),
        "n_shared_events": len(shared_events),
        "truncated": total_eligible > len(candidates),
    }


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def _fingerprint(db: Session, project_id: Optional[int]) -> tuple:
    """Cheap corpus + signal-table fingerprint; changes whenever data changes."""
    from sqlalchemy import func

    from ..models import ProcessedPost, RawPost

    project_id = effective_project_id(db, project_id)
    q = db.query(ProcessedPost.id).join(RawPost, ProcessedPost.raw_id == RawPost.id)
    q = q.filter(ProcessedPost.ae_flag.is_(True))
    sq = db.query(Signal.id)
    tq = db.query(func.max(Signal.updated_at))
    if project_id is not None:
        q = q.filter(RawPost.project_id == project_id)
        sq = sq.filter(Signal.project_id == project_id)
        tq = tq.filter(Signal.project_id == project_id)
    return (project_id, q.count(), sq.count(), str(tq.scalar()))


def _screened(db: Session, project_id: Optional[int]) -> dict:
    key = _fingerprint(db, project_id)
    hit = _CACHE.get(key)
    if hit is None:
        hit = _screen_corpus(db, project_id)
        _CACHE[key] = hit
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return hit


def invalidate_remine_cache() -> None:
    _CACHE.clear()


# --------------------------------------------------------------------------- #
# Public entrypoint — filter / sort / paginate over the screened set
# --------------------------------------------------------------------------- #
_OUTCOME_RANK = {
    "unmasked": 5, "co_reported": 4, "vanished": 3,
    "attenuated": 2, "amplified": 1, "stable": 0,
}
_TIER_RANK = {"evaluable": 2, "provisional": 1, "exploratory": 0}

_SORTS = {
    "impact": lambda c: (
        _OUTCOME_RANK.get(c["outcome"], 0),
        _TIER_RANK.get(c["evidence_tier"], 0),
        abs((c.get("coreporting_ratio") or 1) - 1),
        c.get("target_count") or 0,
    ),
    "coreporting": lambda c: (
        abs((c.get("coreporting_ratio") or 1) - 1), c.get("target_count") or 0,
    ),
    "masking": lambda c: (c.get("masking_ratio") or 0),
    "delta": lambda c: (c.get("delta_prr") or 0),
    "prr": lambda c: (c.get("after_prr") or c.get("before_prr") or 0),
    "count": lambda c: (c.get("target_count") or 0),
    "risk": lambda c: (
        {"high": 3, "moderate": 2, "low": 1}.get(c["masking_risk"], 0),
        c.get("target_count") or 0,
    ),
}

_ONLY_FILTERS = {
    "unmasked": lambda c: c["outcome"] == "unmasked",
    "co_reported": lambda c: c["outcome"] == "co_reported",
    "actionable": lambda c: c["outcome"] in ("unmasked", "co_reported", "vanished"),
    "vanished": lambda c: c["outcome"] == "vanished",
    "attenuated": lambda c: c["outcome"] == "attenuated",
    "amplified": lambda c: c["outcome"] == "amplified",
    "stable": lambda c: c["outcome"] == "stable",
    "evaluable": lambda c: c["evidence_tier"] == "evaluable",
    "devices": lambda c: c["product_type"] == "device",
    "high": lambda c: c["masking_risk"] == "high",
    "moderate": lambda c: c["masking_risk"] == "moderate",
    # legacy alias
    "strengthened": lambda c: c["signal_strengthened"],
}


def build_remine_lab(
    db: Session,
    project_id: Optional[int] = None,
    *,
    limit: int = 24,
    offset: int = 0,
    q: Optional[str] = None,
    only: str = "all",
    sort: str = "impact",
) -> dict:
    screen = _screened(db, project_id)
    cards: List[dict] = screen["cards"]

    matching = cards
    term = (q or "").strip().lower()
    if term:
        matching = [
            c for c in matching
            if term in c["drug"].lower()
            or term in c["event"].lower()
            or any(term in m.lower() for m in c["maskers"])
        ]

    only = (only or "all").lower()
    pred = _ONLY_FILTERS.get(only)
    if pred:
        matching = [c for c in matching if pred(c)]

    matching = sorted(matching, key=_SORTS.get(sort, _SORTS["impact"]), reverse=True)

    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 200))
    page = matching[offset:offset + limit]

    facets = {"all": len(cards)}
    for name, fn in _ONLY_FILTERS.items():
        facets[name] = sum(1 for c in cards if fn(c))

    n_total = len(cards)
    actionable = facets["actionable"]
    if n_total:
        headline = (
            f"{n_total} competition-bias pairs screened from {screen['n_ae_posts']} "
            f"AE posts — {facets['unmasked']} cross the signalling threshold, "
            f"{actionable} need review, {facets['amplified']} move only with the "
            "shared comparator."
        )
    else:
        headline = "No shared events with competitors yet — load the PV demo pack."

    return {
        "cards": page,
        "n_cards": len(page),
        "total_eligible": n_total,
        "total_matching": len(matching),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page) < len(matching),
        "facets": facets,
        "products": screen["products"],
        "events": screen["events"],
        "filters": {"q": q or "", "only": only, "sort": sort},
        "n_reports": screen["n_reports"],
        "needs_demo_seed": n_total < 2,
        "headline": headline,
        "how_to_use": (
            "Search or filter to any product, then Run remine — competitors are "
            "pre-selected. Judge a card on whether it crosses the signalling "
            "threshold, not on raw PRR: PRR rises for every product sharing an event "
            "once the comparator shrinks."
        ),
        "method": {
            "dataset": (
                f"{screen['n_ae_posts']} AE-flagged posts in this workspace → "
                f"{screen['n_reports']} (product, event) report pairs across "
                f"{screen['n_events']} events; {screen['n_shared_events']} events are "
                "reported by two or more products."
            ),
            "eligibility": (
                "A pair is remine-eligible when at least two distinct products report "
                f"the same event, and a masker needs ≥{MIN_MASKER_COUNT} reports of "
                "that event to be credible."
            ),
            "technique": (
                "Case-level competition-bias unmasking (Pariente 2007; Maignen 2014; "
                "ENCePP Ch.11): drop whole reports mentioning a masker, then recompute "
                "PRR/ROR/Yates χ²/EBGM/IC with Haldane-Anscombe +0.5."
            ),
            "metrics": (
                "MR = PRR_after / PRR_before, split exactly into a comparator term "
                "(the classical masking effect, shared by every product on the event) "
                "and a co-reporting term (pair-specific, moves only when the target's "
                "own cases overlap the masker's). MR alone ranks nothing, because it "
                "rises for nearly every pair once the comparator arm shrinks — the "
                "actionable outcome is crossing the signalling threshold."
            ),
            "tiers": (
                "evaluable = ≥3 target cases (Evans criterion), provisional = 2, "
                "exploratory = 1 case (hypothesis-generating only)."
            ),
            "truncated": screen["truncated"],
        },
        "disclaimer": (
            "Sensitivity analysis on the VigilAI corpus — read-only, does not overwrite "
            "stored SDR baselines, and is not a regulatory decision. "
            "Prototype; not for clinical use."
        ),
    }
