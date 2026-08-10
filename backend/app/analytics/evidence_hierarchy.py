"""Evidence hierarchy for ingested VigilAI sources.

Ranks how much *proof weight* a post carries when confirming a safety signal.
This is an evidentiary prior — not a truth oracle. Social media can surface
signals early; peer-reviewed literature and spontaneous reports carry more
confirmatory weight.

Tier scale (descending importance / scale of proof):

  1 · RESEARCH LITERATURE  — peer-reviewed / indexed research articles
      (PubMed, Europe PMC, Semantic Scholar, Cochrane CENTRAL, …)
  2 · REGULATORY / ICSR    — spontaneous reports & official safety notices
      (FAERS, VAERS, MAUDE, FDA MedWatch/recalls, MHRA FSNs, DailyMed labels, FHIR)
  3 · SOCIAL / NEWS        — patient chatter & secondary journalism
      (Reddit, X/Twitter, YouTube, forums, Google News, life-science news, …)

Disproportionality still uses all AE-flagged rows equally in the 2×2 table
(regulator-shaped DMA). Hierarchy is used for:
  • ranking / labeling supporting evidence on Signal Detail
  • weighting thread corroboration confidence
  • analyst triage ("how confirmed is this narrative?")
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# (tier_int, code, label, weight 0–1, plain-language proof note)
_TIER_META = {
    1: {
        "code": "L1_LITERATURE",
        "short": "Research literature",
        "rank_label": "1st — Research articles",
        "weight": 1.0,
        "proof": (
            "Highest confirmatory weight among VigilAI ingest types: indexed / "
            "peer-reviewed research abstracts and trial literature. Still not a "
            "substitute for a full critical appraisal."
        ),
    },
    2: {
        "code": "L2_REGULATORY",
        "short": "Regulatory / ICSR",
        "rank_label": "2nd — Regulatory & spontaneous reports",
        "weight": 0.7,
        "proof": (
            "Medium-high weight: spontaneous ICSRs and official safety communications "
            "(FAERS/VAERS/MAUDE/MHRA/FDA). Confirmatory for signal detection but "
            "subject to reporting bias and incomplete denominators."
        ),
    },
    3: {
        "code": "L3_SOCIAL",
        "short": "Social / news",
        "rank_label": "3rd — Social media & news",
        "weight": 0.35,
        "proof": (
            "Hypothesis-generating only: patient forums, social platforms, and news. "
            "Useful for early detection and patient voice; weakest scale of proof "
            "without corroboration from L1/L2 sources."
        ),
    },
}

# Substring match against RawPost.platform (lowercased)
_L1_MARKERS = (
    "pubmed", "europe_pmc", "europe-pmc", "semantic_scholar", "semantic-scholar",
    "cochrane", "medline", "literature",
)
_L2_MARKERS = (
    "faers", "vaers", "maude", "fda", "mhra", "dailymed", "medwatch",
    "recall", "eudamed", "fhir", "openfda", "icsr", "srs",
)
_L3_MARKERS = (
    "reddit", "twitter", "x.com", "youtube", "forum", "google_news",
    "news", "hackernews", "stream", "forge", "patient", "pullpush",
)


def classify_platform(platform: Optional[str]) -> Tuple[int, str]:
    """Return (tier 1–3, matched_marker). Unknown → tier 3 (conservative)."""
    p = (platform or "").lower().strip()
    if not p:
        return 3, "unknown"
    for m in _L1_MARKERS:
        if m in p:
            return 1, m
    for m in _L2_MARKERS:
        if m in p:
            return 2, m
    for m in _L3_MARKERS:
        if m in p:
            return 3, m
    # Default: treat unfamiliar ingest as social/news (do not over-claim proof)
    return 3, p.split("/")[0][:32] or "other"


def evidence_tier_for_platform(platform: Optional[str]) -> dict:
    tier, marker = classify_platform(platform)
    meta = _TIER_META[tier]
    return {
        "tier": tier,
        "code": meta["code"],
        "short": meta["short"],
        "rank_label": meta["rank_label"],
        "weight": meta["weight"],
        "proof": meta["proof"],
        "platform": platform or "unknown",
        "matched": marker,
    }


def annotate_posts(posts: List[dict]) -> List[dict]:
    """Attach evidence_tier to each post dict; sort L1 → L2 → L3, stable within tier."""
    out = []
    for p in posts:
        tier_info = evidence_tier_for_platform(p.get("platform"))
        q = {**p, "evidence_tier": tier_info}
        out.append(q)
    out.sort(key=lambda x: (x["evidence_tier"]["tier"], -(x.get("ae_confidence") or 0)))
    return out


def evidence_mix(posts: List[dict]) -> dict:
    """Summarise how much of a supporting set sits in each proof tier."""
    counts: Counter = Counter()
    weighted = 0.0
    for p in posts:
        et = p.get("evidence_tier") or evidence_tier_for_platform(p.get("platform"))
        tier = int(et.get("tier") or 3)
        counts[tier] += 1
        weighted += float(et.get("weight") or _TIER_META[3]["weight"])
    n = len(posts) or 1
    mix = {
        "n_posts": len(posts),
        "n_literature": counts[1],
        "n_regulatory": counts[2],
        "n_social": counts[3],
        "mean_proof_weight": round(weighted / n, 3),
        "dominant_tier": (
            1 if counts[1] else (2 if counts[2] else (3 if counts[3] else None))
        ),
        "confirmation_level": _confirmation_level(counts, len(posts)),
        "legend": [
            {"tier": t, **{k: _TIER_META[t][k] for k in (
                "code", "short", "rank_label", "weight", "proof"
            )}}
            for t in (1, 2, 3)
        ],
    }
    return mix


def _confirmation_level(counts: Counter, n: int) -> dict:
    """How 'confirmed' a signal's narrative looks from source mix alone."""
    if counts[1] >= 1 and counts[2] >= 1:
        level, note = "strong", (
            "Corroborated by research literature and regulatory/ICSR sources — "
            "strongest VigilAI confirmation mix."
        )
    elif counts[1] >= 2 or (counts[1] >= 1 and n >= 3):
        level, note = "literature_backed", (
            "Backed by research-article ingest — high literary proof; still review methods."
        )
    elif counts[2] >= 2 or (counts[2] >= 1 and counts[3] >= 1):
        level, note = "regulatory_supported", (
            "Supported by spontaneous reports / official notices; social adds patient voice."
        )
    elif counts[2] >= 1:
        level, note = "regulatory_only", (
            "Regulatory/ICSR only so far — confirmatory for detection, limited literature."
        )
    elif counts[3] >= 1:
        level, note = "hypothesis_generating", (
            "Social/news only — early signal / patient voice; seek L1/L2 corroboration."
        )
    else:
        level, note = "none", "No supporting posts."
    return {"level": level, "note": note}


def tier_weight(platform: Optional[str]) -> float:
    return float(evidence_tier_for_platform(platform)["weight"])
