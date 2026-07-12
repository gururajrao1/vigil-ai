"""Stage 1 — Structural regex sanitization.

Strips non-alphanumeric border symbols, compresses erratic interior spacing,
stitches scrape-broken biomedical compounds (``levofloxac in`` → ``levofloxacin``),
and produces an all-caps alphanumeric baseline key for synonym matching.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import List, NamedTuple, Pattern, Tuple

_WS_RE = re.compile(r"\s+")
_BORDER_JUNK_RE = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")
_INTERIOR_PUNCT_RE = re.compile(r"[^\w\s\-./]+", re.UNICODE)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
# Soft hyphen / zero-width / BOM debris from HTML scrapes
_INVISIBLE_RE = re.compile(r"[\u00ad\u200b\u200c\u200d\ufeff]+")

# Always stitch these class / brand fragments even if absent from the INN lexicon
_EXTRA_COMPOUNDS = (
    "fluoroquinolone",
    "fluoroquinolones",
    "acetaminophen",
    "paracetamol",
    "isotretinoin",
    "accutane",
    "covid-19",
    "myocarditis",
    "pericarditis",
    "rhabdomyolysis",
    "anaphylaxis",
    "stevens-johnson",
)


class Sanitized(NamedTuple):
    """Display-safe cleaned text + uppercase fold key."""

    cleaned: str
    fold_key: str


def strip_border_symbols(value: str) -> str:
    return _BORDER_JUNK_RE.sub("", value or "")


def compress_spacing(value: str) -> str:
    return _WS_RE.sub(" ", (value or "").strip())


def fold_key(value: str) -> str:
    """All-caps alphanumeric baseline (COVID-19 / COVID 19 / COVID19 → COVID19)."""
    if not value:
        return ""
    norm = unicodedata.normalize("NFKD", value)
    ascii_ish = "".join(c for c in norm if not unicodedata.combining(c))
    return _NON_ALNUM_RE.sub("", ascii_ish.upper())


def _single_token_compounds() -> List[str]:
    """Long single-token drug/AE surfaces used to repair scrape-broken words."""
    from .lexicons import GENERIC_DRUGS, SYMPTOMS

    out: set[str] = set(_EXTRA_COMPOUNDS)
    for term in GENERIC_DRUGS:
        t = (term or "").strip().lower()
        if " " not in t and "-" not in t and len(t) >= 8:
            out.add(t)
    for term in SYMPTOMS:
        t = (term or "").strip().lower()
        if " " not in t and "-" not in t and len(t) >= 8:
            out.add(t)
    # longest first so fluoroquinolones wins over fluoroquinolone when overlapping
    return sorted(out, key=len, reverse=True)


@lru_cache(maxsize=1)
def _stitch_patterns() -> Tuple[Tuple[Pattern[str], str], ...]:
    patterns: List[Tuple[Pattern[str], str]] = []
    for compound in _single_token_compounds():
        # Allow optional whitespace between every character: "levofloxac in" → levofloxacin
        body = r"\s*".join(re.escape(ch) for ch in compound)
        patterns.append((
            re.compile(rf"(?i)(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"),
            compound,
        ))
    return tuple(patterns)


def stitch_broken_compounds(value: str) -> str:
    """Join scrape-fragmented biomedical tokens back into lexicon compounds."""
    if not value:
        return ""
    text = _INVISIBLE_RE.sub("", value)
    text = compress_spacing(text)
    if not text:
        return ""
    for pattern, compound in _stitch_patterns():
        def _repl(m: re.Match, canon: str = compound) -> str:
            raw = m.group(0)
            if raw.isupper():
                return canon.upper()
            if raw[:1].isupper():
                return canon[:1].upper() + canon[1:]
            return canon
        text = pattern.sub(_repl, text)
    return compress_spacing(text)


def repair_scraped_text(value: str) -> str:
    """Full pre-NLP / pre-highlight cleanup for messy platform scrapes."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _INVISIBLE_RE.sub("", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = stitch_broken_compounds(text)
    return compress_spacing(text)


def sanitize_surface(value: str) -> Sanitized:
    """Stage-1 entry: border strip → spacing → light punct cleanup → fold key."""
    raw = compress_spacing(strip_border_symbols(repair_scraped_text(value or "")))
    if not raw:
        return Sanitized("", "")
    cleaned = compress_spacing(_INTERIOR_PUNCT_RE.sub(" ", raw))
    return Sanitized(cleaned=cleaned, fold_key=fold_key(cleaned))
