"""Efficient event-label collapse: plurals, ADR clusters, token-set near-dupes.

Used by Stage 2 synonym lookup so filter dropdowns never show
Adverse / Adverse Reaction / Adverse Drug Reactions as separate rows.
"""
from __future__ import annotations

from typing import Optional

from .stage1_sanitize import fold_key, sanitize_surface

# Canonical clinical surface (lowercase) for each cluster
_CLUSTERS: dict[str, frozenset[str]] = {
    # Meta AE wording → one MedDRA-style PT
    "adverse drug reaction": frozenset({
        "ADVERSE",
        "ADR",
        "ADRS",
        "ADVERSEDRUGREACTION",
        "ADVERSEDRUGREACTIONS",
        "ADVERSEREACTION",
        "ADVERSEREACTIONS",
        "ADVERSESIDEEFFECT",
        "ADVERSESIDEEFFECTS",
        "ADVERSEEFFECT",
        "ADVERSEEFFECTS",
        "SIDEEFFECT",
        "SIDEEFFECTS",
        "DRUGREACTION",
        "DRUGREACTIONS",
        "DRUGSIDEEFFECT",
        "DRUGSIDEEFFECTS",
        "MEDICATIONREACTION",
        "MEDICATIONREACTIONS",
        "UNWANTEDEFFECT",
        "UNWANTEDEFFECTS",
    }),
    "allergy": frozenset({
        "ALLER", "ALLERGY", "ALLERGIES", "ALLERGIC", "ALLERGICREACTION",
        "ALLERGICREACTIONS", "HYPERSENSITIVITY", "HYPERSENSITIVITIES",
    }),
    "paraesthesia": frozenset({
        "BRAINZAP", "BRAINZAPS", "PARAESTHESIA", "PARAESTHESIAS",
        "PARESTHESIA", "PARESTHESIAS", "TINGLING", "PINSANDNEEDLES",
    }),
    "diarrhea": frozenset({
        "DIA", "DIARR", "DIARRHEA", "DIARRHOEA", "DIARRHEAS", "DIARRHOEAS",
        "LOOSESTOOL", "LOOSESTOOLS",
    }),
    "nausea": frozenset({
        "NAUSEA", "NAUSEATED", "NAUSEOUS", "QUEASY", "QUEASINESS",
    }),
    "headache": frozenset({
        "HEADACHE", "HEADACHES", "HEADPAIN", "MIGRAINE", "MIGRAINES", "MIG",
    }),
}


def inflection_folds(key: str) -> list[str]:
    """Generate plural/singular fold variants (cheap English morphology)."""
    if not key:
        return []
    out = [key]
    # ies → y (ALLERGIES → ALLERGY)
    if key.endswith("IES") and len(key) > 4:
        out.append(key[:-3] + "Y")
    # es → ∅ (REACTIONS already handled via S; SIDE EFFECTS → …)
    if key.endswith("ES") and len(key) > 4:
        out.append(key[:-2])
        out.append(key[:-1])  # also try single-s
    if key.endswith("S") and not key.endswith("SS") and len(key) > 3:
        out.append(key[:-1])
    # add plural forms of singular
    if not key.endswith("S"):
        out.append(key + "S")
        if key.endswith("Y") and len(key) > 2 and key[-2] not in "AEIOU":
            out.append(key[:-1] + "IES")
        elif key.endswith(("CH", "SH", "X", "Z", "S")):
            out.append(key + "ES")
    # de-dupe preserve order
    seen = set()
    uniq = []
    for k in out:
        if k and k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq


def _token_set(text: str) -> frozenset[str]:
    san = sanitize_surface(text).cleaned.lower()
    return frozenset(t for t in san.replace("-", " ").split() if t)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


# Precompute fold → canonical and token sets for Jaccard fallback
_FOLD_TO_CANON: dict[str, str] = {}
_CANON_TOKENS: list[tuple[str, frozenset[str]]] = []

for _canon, _members in _CLUSTERS.items():
    _CANON_TOKENS.append((_canon, _token_set(_canon)))
    for _m in _members:
        for _v in inflection_folds(_m):
            _FOLD_TO_CANON[_v] = _canon
    for _v in inflection_folds(fold_key(_canon)):
        _FOLD_TO_CANON[_v] = _canon


# High-signal token bags that mean "generic ADR wording" even if word order differs
_ADR_TOKEN_BAGS = (
    frozenset({"adverse", "reaction"}),
    frozenset({"adverse", "reactions"}),
    frozenset({"adverse", "drug", "reaction"}),
    frozenset({"adverse", "drug", "reactions"}),
    frozenset({"adverse", "side", "effect"}),
    frozenset({"adverse", "side", "effects"}),
    frozenset({"adverse", "effect"}),
    frozenset({"adverse", "effects"}),
    frozenset({"side", "effect"}),
    frozenset({"side", "effects"}),
    frozenset({"drug", "reaction"}),
    frozenset({"drug", "reactions"}),
)


def collapse_event_surface(value: str) -> Optional[str]:
    """Return canonical event surface if ``value`` belongs to a known cluster."""
    key = fold_key(value)
    if not key:
        return None

    for variant in inflection_folds(key):
        hit = _FOLD_TO_CANON.get(variant)
        if hit:
            return hit

    tokens = _token_set(value)
    if not tokens:
        return None

    # Exact ADR token-bag match (order-independent)
    for bag in _ADR_TOKEN_BAGS:
        if tokens == bag or bag.issubset(tokens) and len(tokens) <= len(bag) + 1:
            return "adverse drug reaction"

    # Token Jaccard against cluster canon labels
    best_canon, best_score = None, 0.0
    for canon, ctoks in _CANON_TOKENS:
        score = _jaccard(tokens, ctoks)
        if score > best_score:
            best_canon, best_score = canon, score
    if best_score >= 0.75 and best_canon:
        return best_canon

    return None
