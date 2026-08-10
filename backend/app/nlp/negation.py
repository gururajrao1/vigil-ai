"""Rule-based negation detection (ConText / negBio–inspired, offline).

For each symptom span we look backwards for negation cues, and forward for
pseudo-negation / termination that ends the negation scope — the classic
ConText trigger → scope → termination pattern without requiring BioBERT deps.
"""
from __future__ import annotations

import re
from typing import Dict, List

_NEG_CUES = {
    "no", "not", "n't", "never", "without", "denies", "denied", "deny",
    "free", "resolved", "gone", "stopped", "none", "neither", "nor", "absent",
    "negative", "ruled", "exclude", "excluding", "unlikely",
}
_NEG_BIGRAMS = {
    "free from", "no more", "went away", "cleared up", "got rid",
    "rules out", "ruled out", "negative for", "absence of", "denies any",
    "no evidence", "not associated", "without any",
}
# ConText-style terminators — end negation scope when seen after a trigger
_TERMINATORS = {
    "but", "however", "although", "though", "except", "aside",
    "secondary", "cause", "causing", "leads", "leading",
}
# Pseudo-triggers — look like negation but should NOT negate clinical findings
_PSEUDO = {
    "not only", "not just", "no change", "no longer than", "not only because",
}

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def _tokenize_with_offsets(text: str):
    return [(m.group(0).lower(), m.start()) for m in _TOKEN_RE.finditer(text)]


def detect_negation(text: str, symptoms: List[dict], window: int = 6) -> Dict[str, bool]:
    """Return {symptom_normalized: is_negated}."""
    if not text or not symptoms:
        return {}

    tokens = _tokenize_with_offsets(text)
    lower = text.lower()
    result: Dict[str, bool] = {}

    for sym in symptoms:
        negated = False
        start = int(sym.get("start") or 0)
        key = sym.get("normalized") or sym.get("pt") or sym.get("text") or ""
        if not key:
            continue
        # Pseudo-negation window immediately before the span
        pre_wide = lower[max(0, start - 40):start]
        if any(p in pre_wide for p in _PSEUDO):
            result[key] = False
            continue

        sym_idx = 0
        for i, (_, off) in enumerate(tokens):
            if off >= start:
                sym_idx = i
                break

        left = tokens[max(0, sym_idx - window):sym_idx]
        # Walk left-to-right: last trigger wins unless a terminator sits between
        trigger_idx = None
        for i, (w, _) in enumerate(left):
            if w in _NEG_CUES:
                trigger_idx = i
            elif w in _TERMINATORS and trigger_idx is not None:
                trigger_idx = None  # scope closed before symptom
        if trigger_idx is not None:
            negated = True

        if any(bg in pre_wide for bg in _NEG_BIGRAMS):
            negated = True

        result[key] = negated

    return result
