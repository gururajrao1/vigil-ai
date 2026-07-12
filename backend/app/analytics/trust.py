"""Sybil-defense trust score for pharmacovigilance signals.

Inspired by PulseAI's trust scoring approach. Evaluates the cohort of posts
supporting a signal for signs of coordinated inauthentic behaviour:

  trust_score = author_entropy × temporal_spread × text_diversity

Each dimension is normalised 0→1. Final score:
  ≥ 0.70 → high   (diverse organic cohort)
  ≥ 0.40 → medium (some homogeneity, watch)
  ≥ 0.15 → low    (suspicious clustering)
  <  0.15 → sybil  (coordinated burst)

A sybil signal still surfaces (it may be real) but gets a visible downweight
badge so analysts know the cohort looks coordinated.

Deterministic, offline, no external dependencies beyond stdlib + math.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import List, Optional


def _author_entropy(author_hashes: List[str]) -> float:
    """Shannon entropy of author distribution, normalised to [0, 1].

    Uniform distribution (each post from a unique author) → 1.0.
    All posts from one author → 0.0.
    """
    if not author_hashes:
        return 0.0
    n = len(author_hashes)
    counts = Counter(author_hashes)
    entropy = -sum((c / n) * math.log2(c / n) for c in counts.values() if c > 0)
    max_entropy = math.log2(n) if n > 1 else 1.0
    return entropy / max_entropy if max_entropy > 0 else 1.0


def _temporal_spread(timestamps: List[Optional[datetime]]) -> float:
    """Fraction of a 24h window that the posts are spread across.

    Burst (all in <1h) → near 0. Spread over days → 1.0.
    Capped at 1.0 (beyond 24h is fine).
    """
    valid = sorted(t for t in timestamps if t is not None)
    if len(valid) < 2:
        return 1.0  # can't assess with 1 post — assume organic
    span_hours = (valid[-1] - valid[0]).total_seconds() / 3600.0
    # 1h burst = 0.04, 6h = 0.25, 24h = 1.0, >24h = 1.0
    return min(1.0, span_hours / 24.0)


def _text_diversity(texts: List[str]) -> float:
    """Jaccard-based text diversity: how different are the post texts?

    Identical texts (copy-paste sybil) → 0.0.
    All unique → 1.0.
    Uses character 4-gram sets for speed.
    """
    if not texts or len(texts) < 2:
        return 1.0

    def ngrams(s: str, n: int = 4) -> set:
        s = s.lower()[:200]  # cap for speed
        return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}

    bags = [ngrams(t) for t in texts if t]
    if len(bags) < 2:
        return 1.0

    total_similarity = 0.0
    pairs = 0
    for i in range(len(bags)):
        for j in range(i + 1, len(bags)):
            a, b = bags[i], bags[j]
            union = len(a | b)
            if union:
                total_similarity += len(a & b) / union
            pairs += 1

    avg_jaccard = total_similarity / pairs if pairs else 0.0
    return 1.0 - avg_jaccard  # high similarity → low diversity


def compute_trust(
    author_hashes: List[str],
    timestamps: List[Optional[datetime]],
    texts: List[str],
) -> dict:
    """Compute sybil-defense trust score for a signal's supporting cohort.

    Returns {trust_score, trust_label, author_entropy, temporal_spread,
             text_diversity, n_posts, n_unique_authors}.
    """
    n = len(author_hashes)
    if n == 0:
        return {
            "trust_score": 1.0, "trust_label": "high",
            "author_entropy": 1.0, "temporal_spread": 1.0,
            "text_diversity": 1.0, "n_posts": 0, "n_unique_authors": 0,
        }

    ae = _author_entropy(author_hashes)
    ts = _temporal_spread(timestamps)
    td = _text_diversity(texts)

    # Geometric mean — any one dimension collapsing tanks the score
    score = (ae * ts * td) ** (1 / 3)

    if score >= 0.70:
        label = "high"
    elif score >= 0.40:
        label = "medium"
    elif score >= 0.15:
        label = "low"
    else:
        label = "sybil"

    return {
        "trust_score": round(score, 3),
        "trust_label": label,
        "author_entropy": round(ae, 3),
        "temporal_spread": round(ts, 3),
        "text_diversity": round(td, 3),
        "n_posts": n,
        "n_unique_authors": len(set(author_hashes)),
    }
