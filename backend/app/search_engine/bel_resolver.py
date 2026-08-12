"""Step 2 — Fuzzy resolution & Biomedical Entity Linking (MicroMeSH + BEL).

Maps extracted spans to preferred terms and surrogate UMLS CUIs. Semantic
similarity uses a lightweight token Jaccard / character n-gram score offline;
optional scispaCy/BioBERT vectors are used only when importable.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple

from ..nlp.devices import canonical_device, is_known_device
from ..nlp.lexicons import BRAND_TO_GENERIC, GENERIC_DRUGS, SYMPTOMS, normalize_drug
from ..nlp.meddra import map_term
from ..nlp.ontology_engine import crosswalk
from . import dictionary_cache
from .models import ExtractedSpan, LinkedConcept


def _ngrams(text: str, n: int = 3) -> set[str]:
    s = (text or "").lower().strip()
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def fuzzy_score(a: str, b: str) -> float:
    """Hybrid MicroMeSH-style score: sequence ratio + character 3-gram Jaccard."""
    left, right = (a or "").lower().strip(), (b or "").lower().strip()
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    seq = SequenceMatcher(None, left, right).ratio()
    na, nb = _ngrams(left), _ngrams(right)
    jacc = (len(na & nb) / len(na | nb)) if na and nb else 0.0
    return round(0.55 * seq + 0.45 * jacc, 4)


def _optional_embedding_score(a: str, b: str) -> Optional[float]:
    """Cosine over scispaCy vectors when a model with word vectors is available."""
    try:  # pragma: no cover - optional
        import spacy  # noqa: PLC0415

        nlp = None
        for model in ("en_core_sci_md", "en_core_sci_sm"):
            try:
                nlp = spacy.load(model)
                break
            except Exception:
                continue
        if nlp is None:
            return None
        da, db = nlp(a), nlp(b)
        if not getattr(da, "has_vector", False) or not getattr(db, "has_vector", False):
            return None
        if not da.vector_norm or not db.vector_norm:
            return None
        return float(da.similarity(db))
    except Exception:
        return None


def _candidate_pool(kind: str) -> Dict[str, str]:
    """preferred_key → display preferred."""
    if kind == "drug":
        pool = {g: g for g in GENERIC_DRUGS}
        pool.update({b: normalize_drug(b) for b in BRAND_TO_GENERIC})
        pool.update(dictionary_cache.micromesh())
        for brand in dictionary_cache.rxe_brands():
            pool[brand] = brand
        return pool
    if kind == "event":
        pool = {s: s for s in SYMPTOMS}
        pool.update(dictionary_cache.colloquial_ades())
        return pool
    if kind == "device":
        from ..nlp.devices import DEVICE_TO_CANONICAL  # noqa: PLC0415

        return dict(DEVICE_TO_CANONICAL)
    return {}


def fuzzy_lookup(term: str, kind: str = "drug", *, top_n: int = 8,
                 min_score: float = 0.55) -> List[Tuple[str, float]]:
    """Autocomplete / typo suggestions for the Omni-Search dropdown."""
    key = (term or "").strip().lower()
    if not key:
        return []
    mesh = dictionary_cache.micromesh()
    if key in mesh:
        return [(mesh[key], 1.0)]

    scored: List[Tuple[str, float]] = []
    for cand, preferred in _candidate_pool(kind).items():
        score = fuzzy_score(key, cand)
        if score >= min_score:
            scored.append((preferred, score))
    # Deduplicate by preferred, keep best score
    best: Dict[str, float] = {}
    for pref, score in scored:
        best[pref] = max(score, best.get(pref, 0.0))
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:top_n]
    return ranked


def link_span(span: ExtractedSpan) -> LinkedConcept:
    """BEL: verbatim span → preferred concept + surrogate CUI."""
    surface = (span.normalized_hint or span.text or "").strip()
    key = surface.lower()
    kind = span.kind if span.kind in {"drug", "event", "device"} else "unknown"

    # MicroMeSH exact / synonym
    mesh = dictionary_cache.micromesh()
    if key in mesh:
        preferred = mesh[key]
        return LinkedConcept(
            verbatim=span.text,
            preferred=preferred,
            cui=crosswalk.cui_for("drug" if kind != "event" else "event", preferred),
            match_method="micromesh_exact",
            score=0.97,
            kind="drug" if kind != "device" else kind,  # type: ignore[arg-type]
        )

    if kind == "drug" or kind == "substance":
        generic = normalize_drug(key)
        if generic in GENERIC_DRUGS or generic in BRAND_TO_GENERIC.values():
            return LinkedConcept(
                verbatim=span.text,
                preferred=generic,
                cui=crosswalk.cui_for("drug", generic),
                match_method="brand_or_generic_lexicon",
                score=0.93,
                kind="drug",
            )
        hits = fuzzy_lookup(key, "drug", top_n=1, min_score=0.72)
        if hits:
            return LinkedConcept(
                verbatim=span.text,
                preferred=hits[0][0],
                cui=crosswalk.cui_for("drug", hits[0][0]),
                match_method="micromesh_fuzzy",
                score=hits[0][1],
                kind="drug",
            )

    if kind == "event":
        colloquial = dictionary_cache.colloquial_ades()
        if key in colloquial:
            pt = colloquial[key]
            return LinkedConcept(
                verbatim=span.text,
                preferred=pt,
                cui=crosswalk.cui_for("event", pt),
                match_method="cadec_smm4h_surface",
                score=0.9,
                kind="event",
            )
        mapped = map_term(key)
        if mapped.get("matched"):
            return LinkedConcept(
                verbatim=span.text,
                preferred=mapped["pt"],
                cui=crosswalk.cui_for("event", mapped["pt"]),
                match_method="meddra_surrogate",
                score=0.88,
                kind="event",
            )
        hits = fuzzy_lookup(key, "event", top_n=1, min_score=0.7)
        if hits:
            return LinkedConcept(
                verbatim=span.text,
                preferred=hits[0][0],
                cui=crosswalk.cui_for("event", hits[0][0]),
                match_method="event_fuzzy",
                score=hits[0][1],
                kind="event",
            )

    if kind == "device" or is_known_device(key):
        canon = canonical_device(key)
        return LinkedConcept(
            verbatim=span.text,
            preferred=canon,
            cui=crosswalk.cui_for("device", canon),
            match_method="device_lexicon",
            score=0.9,
            kind="device",
        )

    return LinkedConcept(
        verbatim=span.text,
        preferred=surface,
        cui=crosswalk.cui_for("drug", surface),
        match_method="unmatched",
        score=0.0,
        kind=kind if kind != "unknown" else "unknown",  # type: ignore[arg-type]
    )


def link_spans(spans: Sequence[ExtractedSpan]) -> List[LinkedConcept]:
    return [link_span(s) for s in spans]
