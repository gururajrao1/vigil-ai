"""Step 3 — Drug harmonization via RxNorm / RxNorm Extension (RxE).

Resolves brands (including international / discontinued) to brand RxCUI and
Has_Ingredient generics. Offline RxE surrogate is always used; NIH RxNav is an
optional online enricher that never blocks the pipeline.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ..nlp.lexicons import BRAND_TO_GENERIC, DRUG_ATC, atc_for, normalize_drug
from ..nlp.ontology import preferred_generic, resolve_product
from ..nlp.ontology_engine import crosswalk
from . import dictionary_cache
from .models import AuditStamp, BrandChemicalResolution, IngredientRef

logger = logging.getLogger("vigilai.search_engine.rxnorm")


def _audit(online: bool) -> AuditStamp:
    return AuditStamp(
        source="rxe_rxnorm_mapper",
        online_enrichment=online,
        dictionaries=["rxe_extension_surrogate.json", "app.nlp.lexicons", "app.nlp.ontology"],
    )


def _online_rxnorm(term: str) -> dict:
    from ..config import settings  # noqa: PLC0415

    if not settings.use_rxnorm:
        return {}
    try:
        import httpx  # noqa: PLC0415

        base = settings.rxnorm_base_url
        r = httpx.get(f"{base}/approximateTerm.json",
                      params={"term": term, "maxEntries": 1}, timeout=4.0)
        if r.status_code != 200:
            return {}
        cands = r.json().get("approximateGroup", {}).get("candidate", []) or []
        rxcui = cands[0].get("rxcui") if cands else None
        if not rxcui:
            return {}
        r2 = httpx.get(f"{base}/rxcui/{rxcui}/related.json",
                       params={"tty": "IN+PIN+BN"}, timeout=5.0)
        ingredients: List[dict] = []
        brands: List[str] = []
        if r2.status_code == 200:
            for group in r2.json().get("relatedGroup", {}).get("conceptGroup", []) or []:
                tty = group.get("tty")
                for concept in group.get("conceptProperties", []) or []:
                    name = (concept.get("name") or "").strip().lower()
                    cui = concept.get("rxcui")
                    if not name:
                        continue
                    if tty in {"IN", "PIN"}:
                        ingredients.append({"generic": name, "rxcui": f"RXCUI:{cui}",
                                            "rela": "Has_Ingredient"})
                    elif tty == "BN":
                        brands.append(name)
        return {"brand_rxcui": f"RXCUI:{rxcui}", "ingredients": ingredients, "brands": brands}
    except Exception as exc:  # pragma: no cover
        logger.debug("RxNorm online failed for %r: %s", term, exc)
        return {}


def _ingredients_from_rxe(brand_key: str) -> Optional[dict]:
    row = dictionary_cache.rxe_brands().get(brand_key)
    if not row:
        return None
    return row


def subset_brands_for_ingredients(generics: List[str]) -> List[str]:
    index = dictionary_cache.ingredient_brand_index()
    brands: set[str] = set()
    for g in generics:
        brands.update(index.get(g.lower(), []))
    return sorted(brands)


def map_brand_to_ingredients(
    query_term: str,
    *,
    online: bool = False,
) -> BrandChemicalResolution:
    """Resolve a noisy brand / INN to ingredient RxCUIs (Has_Ingredient traversal)."""
    raw = (query_term or "").strip()
    key = raw.lower()
    audit = _audit(online)
    if not key:
        return BrandChemicalResolution(query_term=raw, matched=False,
                                       match_method="empty", audit=audit)

    mesh = dictionary_cache.micromesh()
    folded = mesh.get(key, key)
    rxe = _ingredients_from_rxe(folded) or _ingredients_from_rxe(key)

    method = "unmatched"
    brand_name = None
    brand_rxcui = None
    ingredients: List[IngredientRef] = []
    manufacturers: List[str] = []
    status = None
    regions: List[str] = []

    if rxe:
        brand_name = folded if folded in dictionary_cache.rxe_brands() else key
        brand_rxcui = rxe.get("brand_rxcui")
        manufacturers = list(rxe.get("manufacturer_hints") or [])
        status = rxe.get("status")
        regions = list(rxe.get("regions") or [])
        for ing in rxe.get("ingredients") or []:
            generic = preferred_generic(ing.get("generic"))
            ingredients.append(IngredientRef(
                generic=generic,
                rxcui=ing.get("rxcui"),
                rela=ing.get("rela") or "Has_Ingredient",
                atc=atc_for(generic),
            ))
        method = "rxe_offline"

    if not ingredients:
        concept = resolve_product(folded, online=False)
        generic = concept.preferred_generic or normalize_drug(folded)
        if generic and (generic in DRUG_ATC or generic in BRAND_TO_GENERIC.values()
                        or generic in dictionary_cache.pharmaconer()):
            row = crosswalk.crosswalk_row("drug", generic)
            ingredients.append(IngredientRef(
                generic=generic,
                rxcui=row.get("rxnorm") or concept.rxcui,
                rela="Has_Ingredient",
                atc=concept.atc or atc_for(generic),
            ))
            brand_name = key if key != generic else None
            method = "ontology_offline"

    if online:
        live = _online_rxnorm(raw)
        if live.get("ingredients"):
            method = "rxnorm_online"
            brand_rxcui = brand_rxcui or live.get("brand_rxcui")
            # Prefer online ingredients when they expand a mono → combo or add RxCUIs
            seen = {i.generic for i in ingredients}
            for ing in live["ingredients"]:
                g = preferred_generic(ing["generic"])
                if g in seen:
                    for existing in ingredients:
                        if existing.generic == g and not existing.rxcui:
                            existing.rxcui = ing.get("rxcui")
                    continue
                ingredients.append(IngredientRef(
                    generic=g,
                    rxcui=ing.get("rxcui"),
                    rela="Has_Ingredient",
                    atc=atc_for(g),
                ))
                seen.add(g)

    generics = [i.generic for i in ingredients]
    umls = crosswalk.cui_for("drug", generics[0]) if len(generics) == 1 else (
        crosswalk.cui_for("drug", brand_name or key) if ingredients else None
    )
    subsets = subset_brands_for_ingredients(generics)
    if brand_name and brand_name not in subsets:
        subsets = sorted(set(subsets) | {brand_name})

    return BrandChemicalResolution(
        query_term=raw,
        brand_rxcui=brand_rxcui,
        brand_name=brand_name,
        umls_cui=umls,
        ingredient_rxcuis=[i.rxcui for i in ingredients if i.rxcui],
        ingredients=ingredients,
        atc_classes=sorted({i.atc for i in ingredients if i.atc}),
        manufacturer_hints=manufacturers,
        status=status,
        regions=regions,
        subset_brands=subsets,
        matched=bool(ingredients),
        match_method=method,
        audit=audit,
    )
