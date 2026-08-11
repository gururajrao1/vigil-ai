"""Loader for the offline ontology artifacts under ``app/data/ontology``.

Parquet is preferred when a sibling ``.parquet`` file and pandas are both present
(large deployments can drop in a bigger dictionary without touching code); JSON is
the shipped format. If a file is missing or corrupt the store falls back to
dictionaries already embedded in the NLP modules, so the engine never hard-fails
and the offline-first guarantee holds.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("vigilai.ontology_engine.store")

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "ontology"

_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()
_LOADED_FILES: List[str] = []


def data_dir() -> Path:
    return DATA_DIR


def loaded_dictionaries() -> List[str]:
    """Names of artifacts actually read from disk (audit surface)."""
    return sorted(set(_LOADED_FILES))


def _read_parquet(path: Path) -> Any:
    try:
        import pandas as pd  # noqa: PLC0415 - optional dependency
    except ImportError:
        return None
    try:
        return pd.read_parquet(path).to_dict(orient="records")
    except Exception:
        logger.debug("parquet read failed for %s", path, exc_info=True)
        return None


def _load_file(stem: str) -> Dict[str, Any]:
    parquet = DATA_DIR / f"{stem}.parquet"
    if parquet.exists():
        rows = _read_parquet(parquet)
        if rows is not None:
            _LOADED_FILES.append(parquet.name)
            return {"rows": rows}

    path = DATA_DIR / f"{stem}.json"
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        _LOADED_FILES.append(path.name)
        return payload
    except FileNotFoundError:
        logger.warning("ontology artifact %s missing — using embedded fallback", path.name)
    except Exception:
        logger.warning("ontology artifact %s unreadable — using embedded fallback",
                       path.name, exc_info=True)
    return {}


def load(stem: str) -> Dict[str, Any]:
    """Memoized artifact read. Returns ``{}`` when the file cannot be used."""
    if stem in _CACHE:
        return _CACHE[stem]
    with _LOCK:
        if stem not in _CACHE:
            _CACHE[stem] = _load_file(stem)
    return _CACHE[stem]


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _LOADED_FILES.clear()


# --------------------------------------------------------------------------- #
# Typed accessors with embedded fallbacks
# --------------------------------------------------------------------------- #
def manifest() -> Dict[str, Any]:
    return load("MANIFEST")


def _fallback_meddra_chains() -> List[Dict[str, Any]]:
    """Derive flat chains from the in-module PT/SOC surrogate.

    HLT/HLGT are unavailable in the fallback, so the chain is honestly reported as
    3-tier (LLT/PT/SOC) rather than inventing intermediate groupings.
    """
    from ..meddra import _PT_MAP  # noqa: PLC0415 - internal surrogate table

    by_pt: Dict[str, Dict[str, Any]] = {}
    for surface, (pt, soc_code) in _PT_MAP.items():
        row = by_pt.setdefault(pt, {"pt": pt, "llts": [], "hlt": None,
                                    "hlgt": None, "soc_code": soc_code})
        row["llts"].append(surface)
    return list(by_pt.values())


def meddra_chains() -> List[Dict[str, Any]]:
    payload = load("meddra_hierarchy_surrogate")
    chains = payload.get("chains") or payload.get("rows") or []
    if not chains:
        return _fallback_meddra_chains()
    return chains


def atc_tree() -> Dict[str, Any]:
    payload = load("atc_tree_surrogate")
    if payload.get("levels"):
        return payload
    return {
        "levels": {"1": {}, "2": {}, "3": {}, "4": {}},
        "level_names": {
            "1": "Anatomical main group",
            "2": "Therapeutic subgroup",
            "3": "Pharmacological subgroup",
            "4": "Chemical subgroup",
            "5": "Chemical substance",
        },
    }


def chebi_table() -> Dict[str, Dict[str, Any]]:
    payload = load("chebi_smiles_surrogate")
    table = payload.get("ingredients")
    if table:
        return table
    from ..ontology import _CHEBI_IDS  # noqa: PLC0415 - curated offline IDs

    return {name: {"chebi_id": cid, "smiles": None} for name, cid in _CHEBI_IDS.items()}


def device_table() -> Dict[str, Dict[str, Any]]:
    payload = load("gmdn_emdn_surrogate")
    table = payload.get("devices")
    if table:
        return table
    from ..devices import DEVICE_GMDN  # noqa: PLC0415 - device surrogate

    fallback: Dict[str, Dict[str, Any]] = {}
    for canonical, meta in DEVICE_GMDN.items():
        gmdn = (meta.get("gmdn") or "").split(" / ")
        fallback[canonical] = {
            "gmdn_code": gmdn[0] or None,
            "gmdn_term": canonical.title(),
            "fda_product_code": gmdn[1].replace("FDA-", "") if len(gmdn) > 1 else None,
            "emdn_code": None,
            "emdn_term": None,
            "fda_class": meta.get("class"),
            "eu_mdr_class": None,
            "is_samd": False,
            "implantable": False,
        }
    return fallback


def samd_table() -> Dict[str, Dict[str, Any]]:
    payload = load("gmdn_emdn_surrogate")
    return payload.get("software_as_medical_device") or {}


def cui_anchors() -> Dict[str, Dict[str, Any]]:
    payload = load("umls_cui_surrogate")
    return payload.get("anchors") or {}


def status() -> Dict[str, Any]:
    """Diagnostics for the API/handbook: what loaded, from where, at what version."""
    man = manifest()
    return {
        "data_dir": str(DATA_DIR),
        "ontology_version": man.get("ontology_version", "unknown"),
        "is_surrogate": True,
        "loaded_files": loaded_dictionaries(),
        "counts": {
            "meddra_chains": len(meddra_chains()),
            "atc_level_labels": sum(len(v) for v in atc_tree().get("levels", {}).values()),
            "chebi_ingredients": len(chebi_table()),
            "devices": len(device_table()),
            "samd_categories": len(samd_table()),
            "cui_anchors": len(cui_anchors()),
        },
        "disclaimer": man.get("disclaimer", ""),
    }
