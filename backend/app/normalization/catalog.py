"""Catalog / gazetteer loaders for the MCN surrogate pack."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "normalization"


def _load_json(name: str) -> dict:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    return _load_json("MANIFEST.json")


@lru_cache(maxsize=1)
def load_concept_catalog() -> dict:
    return _load_json("umls_concept_catalog_surrogate.json")


@lru_cache(maxsize=1)
def load_geo_gazetteer() -> dict:
    return _load_json("geo_gazetteer_surrogate.json")


@lru_cache(maxsize=1)
def load_eval_sample() -> dict:
    return _load_json("mantra_cadec_eval_sample.json")


def concept_surfaces() -> List[Tuple[str, dict]]:
    """Flatten preferred + aliases → (surface, concept_row)."""
    rows: List[Tuple[str, dict]] = []
    seen: set[str] = set()
    for concept in load_concept_catalog().get("concepts", []):
        surfaces = [concept.get("preferred", "")] + list(concept.get("aliases") or [])
        for surface in surfaces:
            key = (surface or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append((key, concept))
    return rows


def loaded_files() -> List[str]:
    return sorted(p.name for p in DATA_DIR.glob("*.json"))


def catalog_counts() -> Dict[str, Any]:
    concepts = load_concept_catalog().get("concepts", [])
    places = load_geo_gazetteer().get("places", [])
    eval_pack = load_eval_sample()
    return {
        "concepts": len(concepts),
        "concept_surfaces": len(concept_surfaces()),
        "places": len(places),
        "geo_aliases": sum(len(p.get("aliases") or []) for p in places),
        "eval_clinical_cases": len(eval_pack.get("clinical_cases") or []),
        "eval_geo_cases": len(eval_pack.get("geo_cases") or []),
        "files": loaded_files(),
        "version": load_manifest().get("version"),
    }
