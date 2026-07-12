"""KG briefing from SPARQL subgraph paths — structured, deterministic, no LLM fluff.

Returns a compact analyst briefing: filter context, ranked drug→AE paths with
PRR/strength, and a one-line factual summary. LLM narration is disabled here
because free-text summaries invent clinical tone and bury the numbers.
"""
from __future__ import annotations

from typing import Any, List, Optional


def _rank_paths(paths: List[dict]) -> List[dict]:
    def score(p: dict) -> float:
        prr = float(p.get("prr") or 0)
        strength = {"STRONG": 3, "MODERATE": 2, "WEAK": 1}.get(
            (p.get("strength") or "").upper(), 0
        )
        return prr + strength * 10

    return sorted(paths, key=score, reverse=True)


def build_kg_story(
    paths: List[dict],
    *,
    filters: dict,
    stats: dict,
    allow_llm: bool = False,  # kept for API compat; KG briefing stays deterministic
) -> dict[str, Any]:
    """Return structured briefing for the Knowledge Graph header panel."""
    del allow_llm  # unused — intentional
    active_filters = {
        k: v for k, v in (filters or {}).items() if v and k != "focus_node"
    }
    ranked = _rank_paths([p for p in paths if p.get("drug") and p.get("symptom")])
    top = ranked[:8]

    if not top:
        if active_filters:
            summary = (
                "No drug→AE paths match the current filters. "
                "Clear a filter or ingest more AE-tagged posts for this workspace."
            )
        else:
            summary = (
                "No adverse-event paths in this workspace yet. "
                "Ingest posts / recompute signals, then reopen the graph."
            )
        return {
            "text": summary,
            "source": "briefing",
            "summary": summary,
            "filters": active_filters,
            "path_count": 0,
            "node_count": stats.get("node_count", 0),
            "edge_count": stats.get("edge_count", 0),
            "top_paths": [],
            "disclaimer": (
                "Prototype briefing from social-listening extractions; "
                "PRR can inflate at small N — not for clinical or regulatory use."
            ),
        }

    lead = top[0]
    prr_bit = f", PRR {lead['prr']}" if lead.get("prr") is not None else ""
    strength_bit = f" ({lead.get('strength') or 'WEAK'})" if lead.get("strength") else ""
    filter_bit = (
        f" Filters: {', '.join(f'{k}={v}' for k, v in active_filters.items())}."
        if active_filters
        else ""
    )
    summary = (
        f"{len(ranked)} drug→AE path(s) in view"
        f" ({stats.get('node_count', 0)} nodes / {stats.get('edge_count', 0)} edges)."
        f" Strongest: {lead['drug']} → {lead['symptom']}{prr_bit}{strength_bit}."
        f"{filter_bit}"
    )

    return {
        "text": summary,
        "source": "briefing",
        "summary": summary,
        "filters": active_filters,
        "path_count": len(ranked),
        "node_count": stats.get("node_count", 0),
        "edge_count": stats.get("edge_count", 0),
        "top_paths": [
            {
                "drug": p.get("drug"),
                "symptom": p.get("symptom"),
                "prr": p.get("prr"),
                "strength": p.get("strength"),
                "regions": p.get("regions") or [],
                "condition": p.get("condition"),
            }
            for p in top
        ],
        "disclaimer": (
            "Prototype briefing from social-listening extractions; "
            "PRR can inflate at small N — not for clinical or regulatory use."
        ),
    }
