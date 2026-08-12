"""Query expansion — the operational use of MCN + geo aliases.

Pattabhi (RWD daily meet 2026-08-11): searching «Chennai» must also retrieve
«Madras»; «diabetic» / «Type 2 diabetic mellitus» / «diabetes» collapse to one
cohort; brand search (Janumet) pulls chemical ontology + peer brands.

This module turns those rules into concrete search terms for corpus / signal
retrieval — not a static badge playground.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .geo_normalizer import get_geo_normalizer, normalize_location
from .models import GeoResolution
from .umls_linker import link_to_umls


_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]{1,40}")


def _tokens(text: str) -> List[str]:
    return _WORD.findall(text or "")


def expand_geo_terms(text: str) -> Dict[str, object]:
    """Detect municipal aliases in free text and expand to the full synonym set."""
    geo = get_geo_normalizer()
    found: List[dict] = []
    all_aliases: Set[str] = set()
    blob = (text or "").strip()
    if not blob:
        return {"matches": [], "search_terms": [], "canonical_cities": []}

    # Prefer longest alias surfaces first (Ho Chi Minh City before City)
    surfaces = sorted(geo._alias_index.keys(), key=len, reverse=True)
    lowered = blob.lower()
    consumed: List[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= a or start >= b) for a, b in consumed)

    for surface in surfaces:
        if len(surface) < 3:
            continue
        start = 0
        while True:
            idx = lowered.find(surface, start)
            if idx < 0:
                break
            end = idx + len(surface)
            # word-ish boundary
            before = lowered[idx - 1] if idx > 0 else " "
            after = lowered[end] if end < len(lowered) else " "
            if before.isalnum() or after.isalnum():
                start = idx + 1
                continue
            if _overlaps(idx, end):
                start = idx + 1
                continue
            place = geo._alias_index[surface]
            resolution = normalize_location(surface)
            aliases = sorted({
                *(a.lower() for a in (place.get("aliases") or [])),
                (place.get("canonical") or "").lower(),
            } - {""})
            found.append({
                "verbatim": blob[idx:end],
                "canonical": place.get("canonical"),
                "aliases": aliases,
                "country": place.get("country"),
                "lat": place.get("lat"),
                "lon": place.get("lon"),
                "why": (
                    f"«{place.get('canonical')}» and historical/alternate names "
                    f"({', '.join(aliases[:6])}) refer to the same place — "
                    "search expands to all so Madras-tagged reports appear under Chennai."
                ),
                "resolution": resolution.model_dump(),
            })
            all_aliases.update(aliases)
            consumed.append((idx, end))
            start = end

    # Also try the whole string as a bare city query
    if not found and len(blob.split()) <= 4:
        bare = normalize_location(blob)
        if bare.matched and bare.canonical:
            place = geo._alias_index.get((bare.alias_used or "").lower()) or {}
            aliases = sorted({
                *(a.lower() for a in (place.get("aliases") or [])),
                bare.canonical.lower(),
            } - {""})
            found.append({
                "verbatim": blob,
                "canonical": bare.canonical,
                "aliases": aliases,
                "country": bare.country,
                "lat": bare.lat,
                "lon": bare.lon,
                "why": (
                    f"Location query expanded: searching «{bare.canonical}» also "
                    f"matches {', '.join(aliases)}."
                ),
                "resolution": bare.model_dump(),
            })
            all_aliases.update(aliases)

    return {
        "matches": found,
        "search_terms": sorted(all_aliases),
        "canonical_cities": sorted({m["canonical"] for m in found if m.get("canonical")}),
    }


def expand_clinical_terms(text: str) -> Dict[str, object]:
    """Map colloquial / fragmented disease mentions onto one CUI + synonym bag."""
    blob = (text or "").strip()
    matches: List[dict] = []
    terms: Set[str] = set()
    if not blob:
        return {"matches": [], "search_terms": [], "preferred_pts": [], "cuis": []}

    # Whole-string first (handles multi-word slang)
    candidates = [blob]
    # Sliding bigrams / unigrams for embedded slang
    toks = _tokens(blob)
    for i in range(len(toks)):
        candidates.append(toks[i])
        if i + 1 < len(toks):
            candidates.append(f"{toks[i]} {toks[i + 1]}")
        if i + 2 < len(toks):
            candidates.append(f"{toks[i]} {toks[i + 1]} {toks[i + 2]}")

    seen_cui: Set[str] = set()
    for cand in candidates:
        link = link_to_umls(cand)
        if not link.matched or not link.cui or link.cui in seen_cui:
            continue
        # Prefer phrase matches over single noisy tokens unless exact alias
        if len(cand.split()) == 1 and link.match_method.startswith("dense"):
            continue
        seen_cui.add(link.cui)
        from . import catalog

        concept = next(
            (c for c in catalog.load_concept_catalog().get("concepts", []) if c["cui"] == link.cui),
            None,
        )
        aliases = []
        if concept:
            aliases = [concept.get("preferred", "")] + list(concept.get("aliases") or [])
        aliases = sorted({a.lower() for a in aliases if a})
        matches.append({
            "verbatim": cand,
            "cui": link.cui,
            "preferred": link.preferred,
            "meddra_pt": link.meddra_pt,
            "snomed_ct": link.snomed_ct,
            "aliases": aliases,
            "patient_count_rule": (
                "Sum discrete counts across all aliases onto this CUI before "
                "disproportionality (e.g. diabetic 2 + T2DM 3 + diabetes 5 → N=10)."
            ),
            "why": (
                f"«{cand}» normalizes to MedDRA PT «{link.meddra_pt}» "
                f"({link.cui}); vertical frequency tables must not split synonyms."
            ),
        })
        terms.update(aliases)
        if link.meddra_pt:
            terms.add(link.meddra_pt.lower())

    return {
        "matches": matches,
        "search_terms": sorted(terms),
        "preferred_pts": sorted({m["meddra_pt"] for m in matches if m.get("meddra_pt")}),
        "cuis": sorted(seen_cui),
    }


def expand_query(text: str, *, online: bool = False) -> dict:
    """Full expansion for Omni-Search / Detect: brand + clinical + geo."""
    from ..search_engine import resolve_brand_to_chemical

    brand = resolve_brand_to_chemical(text, online=online)
    if not brand.matched:
        # Multi-token queries ("Janumet diabetes Madras") — try each token / bigram.
        toks = _tokens(text)
        for cand in list(toks) + [f"{a} {b}" for a, b in zip(toks, toks[1:])]:
            hit = resolve_brand_to_chemical(cand, online=online)
            if hit.matched:
                brand = hit
                break

    geo = expand_geo_terms(text)
    clinical = expand_clinical_terms(text)

    search_terms: Set[str] = set()
    # Always include the raw query
    if (text or "").strip():
        search_terms.add(text.strip().lower())
    search_terms.update(geo.get("search_terms") or [])
    search_terms.update(clinical.get("search_terms") or [])

    brand_terms: List[str] = []
    if brand.matched:
        if brand.brand_name:
            brand_terms.append(brand.brand_name)
            search_terms.add(brand.brand_name.lower())
        for ing in brand.ingredients or []:
            brand_terms.append(ing.generic)
            search_terms.add(ing.generic.lower())
        for b in brand.subset_brands or []:
            brand_terms.append(b)
            search_terms.add(b.lower())

    why: List[str] = []
    for m in geo.get("matches") or []:
        why.append(m["why"])
    for m in clinical.get("matches") or []:
        why.append(m["why"])
    if brand.matched:
        ings = ", ".join(i.generic for i in (brand.ingredients or [])[:4]) or "chemical ingredients"
        peers = ", ".join((brand.subset_brands or [])[:4]) or "peer brands"
        why.append(
            f"Brand «{brand.brand_name or text}» → {ings}. "
            f"Universe = chemical class; Subset = {peers} (compare formulations)."
        )

    return {
        "query": text,
        "geo": geo,
        "clinical": clinical,
        "brand": brand.model_dump() if hasattr(brand, "model_dump") else brand,
        "brand_terms": brand_terms,
        "search_terms": sorted(t for t in search_terms if t),
        "why": why,
        "useful_for": [
            "Corpus narrative search (title/body) — geo + clinical aliases",
            "Signal Detect filter — event PT synonyms do not fragment",
            "Universe vs Subset DMA — brand peers share chemical ontology",
            "Cohort N for disproportionality — sum synonym patient counts",
        ],
    }
