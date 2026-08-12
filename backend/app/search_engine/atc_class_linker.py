"""Step 4 — Therapeutic class linkage (RxClass / ATC).

Links resolved ingredient RxCUIs to WHO ATC classifications. Offline path uses
the curated DRUG_ATC table + ontology_engine ATC ladder; optional RxClass REST
enrichment runs only when online=True.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from ..nlp.lexicons import atc_for
from ..nlp.ontology_engine.drug_chemical_mapper import atc_class_members, atc_levels
from .models import BrandChemicalResolution, IngredientRef

logger = logging.getLogger("vigilai.search_engine.atc")


def _rxclass_online(rxcui: str) -> List[dict]:
    """Optional NIH RxClass lookup by RxCUI (keyless)."""
    from ..config import settings  # noqa: PLC0415

    if not settings.use_rxnorm:
        return []
    # Strip surrogate prefixes for live API
    numeric = "".join(ch for ch in (rxcui or "") if ch.isdigit())
    if not numeric:
        return []
    try:
        import httpx  # noqa: PLC0415

        r = httpx.get(
            f"{settings.rxnorm_base_url}/rxclass/class/byRxcui.json",
            params={"rxcui": numeric, "relaSource": "ATC"},
            timeout=5.0,
        )
        if r.status_code != 200:
            return []
        out = []
        for item in (r.json().get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo", []) or []:
            mini = item.get("rxclassMinConceptItem") or {}
            out.append({
                "class_id": mini.get("classId"),
                "class_name": mini.get("className"),
                "class_type": mini.get("classType"),
            })
        return out
    except Exception as exc:  # pragma: no cover
        logger.debug("RxClass online failed for %r: %s", rxcui, exc)
        return []


def link_atc(
    ingredients: Sequence[IngredientRef],
    *,
    online: bool = False,
) -> List[dict]:
    """Return ATC ladder detail for each ingredient (+ optional RxClass classes)."""
    detail: List[dict] = []
    for ing in ingredients:
        code = ing.atc or atc_for(ing.generic)
        levels = [lvl.model_dump() for lvl in atc_levels(code)] if code else []
        rxclass = []
        if online and ing.rxcui:
            rxclass = _rxclass_online(ing.rxcui)
        detail.append({
            "generic": ing.generic,
            "rxcui": ing.rxcui,
            "atc_code": code,
            "atc_levels": levels,
            "class_members": atc_class_members(code[:4]) if code and len(code) >= 4 else [],
            "rxclass": rxclass,
        })
    return detail


def enrich_resolution(
    resolution: BrandChemicalResolution,
    *,
    online: bool = False,
) -> BrandChemicalResolution:
    """Attach ATC ladder detail onto an existing brand→chemical resolution."""
    detail = link_atc(resolution.ingredients, online=online)
    codes = sorted({d["atc_code"] for d in detail if d.get("atc_code")})
    return resolution.model_copy(update={
        "atc_classes": codes or resolution.atc_classes,
        "atc_detail": detail,
        "audit": resolution.audit.model_copy(update={"online_enrichment": online}),
    })
