"""Step 1 — Ingestion & extraction over noisy patient / forum text.

PharmaCoNER-style substance NER + CADEC/SMM4H colloquial ADE surfaces, with the
existing VigilAI lexicons as the offline backbone. Optional transformer NER is
attempted when configured; failure never blocks the offline path.
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..nlp.devices import DEVICE_TO_CANONICAL, extract_devices
from ..nlp.lexicons import BRAND_TO_GENERIC, GENERIC_DRUGS, SYMPTOMS
from . import dictionary_cache
from .models import ExtractedSpan


def _clean(text: str) -> str:
    return (text or "").strip()


def _window_negated(text: str, start: int, cues: List[str], window: int = 28) -> bool:
    left = text[max(0, start - window):start].lower()
    return any(re.search(rf"\b{re.escape(c)}\b", left) for c in cues)


def _matcher(terms) -> Optional[re.Pattern]:
    terms = [t for t in terms if t and len(t) >= 2]
    if not terms:
        return None
    ordered = sorted(set(terms), key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in ordered) + r")(?!\w)",
                      re.IGNORECASE)


def _optional_transformer_spans(text: str) -> List[ExtractedSpan]:
    """Best-effort BioBERT/scispaCy-class NER when USE_TRANSFORMER_NER is on."""
    from ..config import settings  # noqa: PLC0415

    if not settings.use_transformer_ner:
        return []
    try:  # pragma: no cover - optional heavy dependency
        from ..nlp.ner import extract_entities  # type: ignore

        ents = extract_entities(text) or {}
        out: List[ExtractedSpan] = []
        for drug in ents.get("drugs") or []:
            out.append(ExtractedSpan(
                text=drug.get("text") or "",
                start=int(drug.get("start") or 0),
                end=int(drug.get("end") or 0),
                kind="drug",
                confidence=float(drug.get("score") or 0.7),
                source="transformer_ner",
                normalized_hint=drug.get("normalized") or drug.get("generic"),
            ))
        for sym in ents.get("symptoms") or []:
            out.append(ExtractedSpan(
                text=sym.get("text") or "",
                start=int(sym.get("start") or 0),
                end=int(sym.get("end") or 0),
                kind="event",
                confidence=float(sym.get("score") or 0.65),
                source="transformer_ner_smm4h_calibrated",
                normalized_hint=sym.get("normalized") or sym.get("pt"),
            ))
        return out
    except Exception:
        return []


def extract_spans(text: str) -> List[ExtractedSpan]:
    """Extract drug / substance / ADE / device spans from noisy verbatim text."""
    blob = _clean(text)
    if not blob:
        return []

    cues = dictionary_cache.negation_cues()
    colloquial = dictionary_cache.colloquial_ades()
    pharma = dictionary_cache.pharmaconer()
    micromesh = dictionary_cache.micromesh()
    rxe = dictionary_cache.rxe_brands()

    drug_terms = set(GENERIC_DRUGS) | set(BRAND_TO_GENERIC) | set(pharma) | set(rxe) | set(micromesh)
    event_terms = set(SYMPTOMS) | set(colloquial)
    device_terms = set(DEVICE_TO_CANONICAL)

    spans: List[ExtractedSpan] = []
    seen: set[tuple] = set()

    def _add(surface: str, start: int, end: int, kind: str, conf: float, source: str, hint=None):
        key = (kind, surface.lower(), start)
        if key in seen:
            return
        if _window_negated(blob, start, cues):
            return
        seen.add(key)
        spans.append(ExtractedSpan(
            text=surface,
            start=start,
            end=end,
            kind=kind,  # type: ignore[arg-type]
            confidence=conf,
            source=source,
            normalized_hint=hint,
        ))

    for pattern, kind, source, conf, hint_fn in (
        (_matcher(drug_terms), "drug", "pharmaconer_lexicon", 0.85,
         lambda s: pharma.get(s.lower(), {}).get("generic")
         or micromesh.get(s.lower())
         or BRAND_TO_GENERIC.get(s.lower())),
        (_matcher(event_terms), "event", "cadec_smm4h_lexicon", 0.8,
         lambda s: colloquial.get(s.lower()) or colloquial.get(s)),
        (_matcher(device_terms), "device", "device_lexicon", 0.85,
         lambda s: DEVICE_TO_CANONICAL.get(s.lower())),
    ):
        if not pattern:
            continue
        for m in pattern.finditer(blob):
            surface = m.group(0)
            _add(surface, m.start(), m.end(), kind, conf, source, hint_fn(surface))

    # Multi-word colloquial ADE phrases (CADEC-style) not covered by single tokens
    low = blob.lower()
    for phrase, pt in sorted(colloquial.items(), key=lambda kv: -len(kv[0])):
        if len(phrase) < 6 or phrase not in low:
            continue
        idx = low.find(phrase)
        if idx >= 0:
            _add(blob[idx:idx + len(phrase)], idx, idx + len(phrase),
                 "event", 0.75, "cadec_phrase", pt)

    for span in _optional_transformer_spans(blob):
        _add(span.text, span.start, span.end, span.kind, span.confidence,
             span.source, span.normalized_hint)

    # Device extractor as a second pass for brand/model fragments
    try:
        for prod in extract_devices(blob).get("products") or []:
            _add(prod.get("text") or prod.get("normalized") or "",
                 int(prod.get("start") or 0), int(prod.get("end") or 0),
                 "device", 0.8, prod.get("source") or "device_lexicon",
                 prod.get("normalized"))
    except Exception:
        pass

    spans.sort(key=lambda s: (-s.confidence, s.start))
    return spans
