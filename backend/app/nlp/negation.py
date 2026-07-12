"""Rule-based negation detection over a sliding window.

For each symptom span we look backwards a few tokens for a negation cue. This is
the offline analog of medspaCy/negspaCy context detection.
"""
from __future__ import annotations

import re
from typing import Dict, List

_NEG_CUES = {
    "no", "not", "n't", "never", "without", "denies", "denied", "deny",
    "free", "resolved", "gone", "stopped", "none", "neither", "nor", "absent",
}
_NEG_BIGRAMS = {"free from", "no more", "went away", "cleared up", "got rid"}

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def _tokenize_with_offsets(text: str):
    return [(m.group(0).lower(), m.start()) for m in _TOKEN_RE.finditer(text)]


def detect_negation(text: str, symptoms: List[dict], window: int = 4) -> Dict[str, bool]:
    """Return {symptom_normalized: is_negated}."""
    if not text or not symptoms:
        return {}

    tokens = _tokenize_with_offsets(text)
    lower = text.lower()
    result: Dict[str, bool] = {}

    for sym in symptoms:
        negated = False
        # token index of the symptom start
        start = sym["start"]
        sym_idx = 0
        for i, (_, off) in enumerate(tokens):
            if off >= start:
                sym_idx = i
                break
        left = tokens[max(0, sym_idx - window):sym_idx]
        left_words = {w for w, _ in left}
        if left_words & _NEG_CUES:
            negated = True
        # bigram cues anywhere shortly before the symptom
        pre = lower[max(0, start - 25):start]
        if any(bg in pre for bg in _NEG_BIGRAMS):
            negated = True
        result[sym["normalized"]] = negated

    return result
