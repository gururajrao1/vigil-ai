"""Omni-Search gateway — orchestrates the 5-step brand→chemical pipeline.

1. extractor       — PharmaCoNER / CADEC / SMM4H calibrated span extraction
2. bel_resolver    — MicroMeSH fuzzy + BEL → CUI
3. rxnorm_mapper   — RxNorm / RxE Has_Ingredient resolution
4. atc_class_linker — RxClass / ATC ladder
5. omop_analytics  — Universe vs Subset disproportionality
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from . import (
    atc_class_linker,
    bel_resolver,
    dictionary_cache,
    extractor,
    omop_analytics,
    rxnorm_mapper,
)
from .models import (
    SEARCH_DISCLAIMER,
    SEARCH_VERSION,
    AuditStamp,
    BrandChemicalResolution,
    OmniSearchResult,
    UniverseSubsetReport,
)

__all__ = [
    "omni_search",
    "resolve_brand_to_chemical",
    "autocomplete",
    "engine_status",
    "SEARCH_VERSION",
    "SEARCH_DISCLAIMER",
]


def resolve_brand_to_chemical(
    query_term: str,
    *,
    online: bool = False,
) -> BrandChemicalResolution:
    """Public MCP/API helper: noisy brand → CUI + ingredient RxCUIs + ATC."""
    resolution = rxnorm_mapper.map_brand_to_ingredients(query_term, online=online)
    return atc_class_linker.enrich_resolution(resolution, online=online)


def autocomplete(query_term: str, *, kind: str = "drug", limit: int = 8) -> List[dict]:
    """Fuzzy suggestions for the Omni-Search dropdown."""
    hits = bel_resolver.fuzzy_lookup(query_term, kind=kind, top_n=limit)
    return [{"term": term, "score": score, "kind": kind} for term, score in hits]


def omni_search(
    query: str,
    *,
    db: Optional[Session] = None,
    online: bool = False,
    subset_brands: Optional[Sequence[str]] = None,
    project_id: Optional[int] = None,
    include_analytics: bool = True,
) -> OmniSearchResult:
    """Run the full 5-step pipeline for one Omni-Search query."""
    audit = AuditStamp(
        online_enrichment=online,
        dictionaries=dictionary_cache.loaded_files(),
    )
    q = (query or "").strip()
    notes: List[str] = []
    if not q:
        return OmniSearchResult(
            query="",
            notes=["Empty query."],
            audit=audit,
        )

    spans = extractor.extract_spans(q)
    linked = bel_resolver.link_spans(spans)
    # Prefer drug-linked concept for resolution; else the raw query
    drug_link = next((c for c in linked if c.kind == "drug" and c.score > 0), None)
    resolve_term = drug_link.preferred if drug_link else q
    resolution = resolve_brand_to_chemical(resolve_term, online=online)
    if not resolution.matched:
        # try original query (combo brands like Janumet)
        resolution = resolve_brand_to_chemical(q, online=online)

    suggestions = autocomplete(q, kind="drug")
    if not suggestions and drug_link:
        suggestions = autocomplete(drug_link.preferred, kind="drug")

    analytics: Optional[UniverseSubsetReport] = None
    if include_analytics and db is not None and resolution.matched:
        analytics = omop_analytics.compute_universe_vs_subset(
            db,
            resolution,
            subset_brands=subset_brands,
            project_id=project_id,
        )
    elif include_analytics and db is None:
        notes.append("Analytics skipped — no DB session (resolution-only mode).")

    if not resolution.matched:
        notes.append(
            "No brand/ingredient match in RxE or offline lexicons. "
            "Try a known brand (Janumet, Ozempic, Coumadin) or generic."
        )
    if resolution.status == "discontinued":
        notes.append(
            f"«{resolution.brand_name}» is marked discontinued in the RxE surrogate — "
            "ingredient mapping is retained for historical surveillance."
        )

    # Pattabhi: expand geo (Chennai≡Madras) + clinical synonyms + brand peers,
    # then retrieve corpus posts/signals matching ANY expanded term.
    expansions = None
    corpus_hits = None
    try:
        from ..normalization import expand_query, search_corpus_with_expansion

        expansions = expand_query(q, online=online)
        for reason in expansions.get("why") or []:
            notes.append(reason)
        if db is not None:
            corpus_hits = search_corpus_with_expansion(
                db, q, project_id=project_id, online=online
            )
            if corpus_hits.get("n_posts") == 0 and corpus_hits.get("n_signals") == 0:
                notes.append(
                    "No corpus hits for expanded terms yet — load the PV demo pack "
                    "or ingest narratives that mention these aliases."
                )
    except Exception as exc:  # noqa: BLE001 — never break Omni-Search on MCN
        notes.append(f"Expansion overlay unavailable: {exc}")

    return OmniSearchResult(
        query=q,
        extracted=spans,
        linked=linked,
        resolution=resolution,
        suggestions=suggestions,
        universe_subset=analytics,
        expansions=expansions,
        corpus_hits=corpus_hits,
        notes=notes,
        audit=audit,
    )


def engine_status() -> dict:
    return {
        **dictionary_cache.status(),
        "pipeline": [
            "1 extractor (PharmaCoNER + CADEC/SMM4H surrogates)",
            "2 bel_resolver (MicroMeSH fuzzy + CUI)",
            "3 rxnorm_mapper (RxE offline + optional RxNav)",
            "4 atc_class_linker (ATC ladder + optional RxClass)",
            "5 omop_analytics (Universe vs Subset DMA)",
        ],
    }
