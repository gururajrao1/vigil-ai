"""Colloquial -> MedDRA vernacular mapping.

Patients describe adverse events in everyday language, not MedDRA. This module
maps common English idioms/slang to a canonical symptom surface that
``meddra.map_term`` recognizes, so social posts written in plain language still
yield a standardized Preferred Term + System Organ Class. Deterministic + offline;
the original patient phrase is preserved for traceability ("we understood the
patient's own words").

Phrases are chosen to be specific enough to avoid false positives (ambiguous words
like "sick" are deliberately excluded in favour of clear idioms).
"""
from __future__ import annotations

import re
from typing import Dict, List

# colloquial phrase (lowercase) -> canonical symptom surface known to meddra._PT_MAP
VERNACULAR: Dict[str, str] = {
    # cardiac
    "heart was pounding": "palpitations",
    "heart was racing": "palpitations",
    "heart pounding": "palpitations",
    "racing heart": "palpitations",
    "heart skipping beats": "palpitations",
    "heart fluttering": "palpitations",
    # neuro / cognitive
    "foggy head": "brain fog",
    "can't think straight": "brain fog",
    "cant think straight": "brain fog",
    "mentally foggy": "brain fog",
    "pins and needles": "tingling",
    "brain zaps": "paresthesia",
    "brain zap": "paresthesia",
    "electric shocks in head": "paresthesia",
    "room was spinning": "dizziness",
    "room spinning": "dizziness",
    "everything was spinning": "dizziness",
    "lightheaded": "dizziness",
    "light headed": "dizziness",
    "shaky hands": "tremor",
    "hands were shaking": "tremor",
    "hands shaking": "tremor",
    "trembling": "tremor",
    "splitting headache": "headache",
    "pounding headache": "headache",
    # sleep / psych
    "couldn't sleep a wink": "insomnia",
    "couldn't sleep": "insomnia",
    "couldnt sleep": "insomnia",
    "can't sleep": "insomnia",
    "cant sleep": "insomnia",
    "up all night": "insomnia",
    "felt down": "depression",
    "feeling down": "depression",
    "really low": "depression",
    "hopeless": "depression",
    "in a dark place": "depression",
    "on edge": "anxiety",
    # somnolence / fatigue
    "knocked out": "drowsiness",
    "like a zombie": "drowsiness",
    "couldn't stay awake": "drowsiness",
    "so drowsy": "drowsiness",
    "wiped out": "fatigue",
    "no energy": "fatigue",
    "exhausted": "fatigue",
    "drained": "fatigue",
    "worn out": "fatigue",
    # GI
    "the runs": "diarrhea",
    "loose motions": "diarrhea",
    "throwing up": "vomiting",
    "threw up": "vomiting",
    "puking": "vomiting",
    "queasy": "nausea",
    "stomach in knots": "stomach pain",
    "gut ache": "stomach pain",
    "belly ache": "stomach pain",
    # skin / immune
    "itchy all over": "itching",
    "so itchy": "itching",
    "broke out in hives": "hives",
    "puffy face": "swollen face",
    "face swelled up": "swollen face",
    "face blew up": "swollen face",
    # respiratory
    "can't catch my breath": "shortness of breath",
    "cant catch my breath": "shortness of breath",
    "short of breath": "shortness of breath",
    "gasping for air": "shortness of breath",
    # musculoskeletal
    "muscles are killing me": "muscle pain",
    "muscle aches": "muscle pain",
    "legs feel like lead": "muscle pain",
    "aching muscles": "muscle pain",
    # vascular / general
    "swollen ankles": "swollen ankles",
    "puffy ankles": "swollen ankles",
}


def _build_matcher(phrases) -> re.Pattern:
    # Longest-first so multi-word idioms win over any substring.
    ordered = sorted(phrases, key=len, reverse=True)
    escaped = [re.escape(p) for p in ordered]
    # Word-edge lookarounds (handle apostrophes/spaces without \b pitfalls).
    return re.compile(r"(?<!\w)(" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)


_VERN_RE = _build_matcher(VERNACULAR.keys())

# fold_key → canonical so apostrophe/spacing variants still resolve
from .stage1_sanitize import fold_key as _fold_key

_VERN_BY_FOLD: Dict[str, str] = {
    _fold_key(phrase): canon for phrase, canon in VERNACULAR.items()
}


def vernacular_lookup(surface: str) -> str | None:
    """Resolve a patient phrase to a lexicon surface, tolerant of apostrophes."""
    if not surface:
        return None
    low = surface.strip().lower()
    if low in VERNACULAR:
        return VERNACULAR[low]
    return _VERN_BY_FOLD.get(_fold_key(surface))


def scan(text: str) -> List[dict]:
    """Return matched vernacular spans: {phrase, canonical, start, end}."""
    if not text:
        return []
    out: List[dict] = []
    for m in _VERN_RE.finditer(text):
        phrase = m.group(0)
        canonical = VERNACULAR.get(phrase.lower()) or vernacular_lookup(phrase)
        if canonical:
            out.append({
                "phrase": phrase,
                "canonical": canonical,
                "start": m.start(),
                "end": m.end(),
            })
    return out
