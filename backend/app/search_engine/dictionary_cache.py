"""Offline dictionary loader for Omni-Search surrogates (JSON; Parquet optional)."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("vigilai.search_engine.cache")

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "search"
_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()
_LOADED: List[str] = []


def loaded_files() -> List[str]:
    return sorted(set(_LOADED))


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _LOADED.clear()


def _load(stem: str) -> Dict[str, Any]:
    parquet = DATA_DIR / f"{stem}.parquet"
    if parquet.exists():
        try:
            import pandas as pd  # noqa: PLC0415

            rows = pd.read_parquet(parquet).to_dict(orient="records")
            _LOADED.append(parquet.name)
            return {"rows": rows}
        except Exception:
            logger.debug("parquet read failed for %s", parquet, exc_info=True)

    path = DATA_DIR / f"{stem}.json"
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        _LOADED.append(path.name)
        return payload
    except FileNotFoundError:
        logger.warning("search artifact %s missing", path.name)
    except Exception:
        logger.warning("search artifact %s unreadable", path.name, exc_info=True)
    return {}


def load(stem: str) -> Dict[str, Any]:
    if stem in _CACHE:
        return _CACHE[stem]
    with _LOCK:
        if stem not in _CACHE:
            _CACHE[stem] = _load(stem)
    return _CACHE[stem]


def micromesh() -> Dict[str, str]:
    payload = load("micromesh_synonyms_surrogate")
    out = dict(payload.get("synonyms") or {})
    out.update(payload.get("abbreviations") or {})
    return {k.lower(): v for k, v in out.items()}


def colloquial_ades() -> Dict[str, str]:
    payload = load("cadec_smm4h_colloquial_surrogate")
    out = dict(payload.get("ade_surfaces") or {})
    out.update(payload.get("emoji_cues") or {})
    return out


def negation_cues() -> List[str]:
    payload = load("cadec_smm4h_colloquial_surrogate")
    return list(payload.get("negation_cues") or [])


def pharmaconer() -> Dict[str, dict]:
    payload = load("pharmaconer_substances_surrogate")
    return {k.lower(): v for k, v in (payload.get("substances") or {}).items()}


def combo_brands() -> Dict[str, List[str]]:
    payload = load("pharmaconer_substances_surrogate")
    return {k.lower(): list(v) for k, v in (payload.get("combo_brands") or {}).items()}


def rxe_brands() -> Dict[str, dict]:
    payload = load("rxe_extension_surrogate")
    return {k.lower(): v for k, v in (payload.get("brands") or {}).items()}


def ingredient_brand_index() -> Dict[str, List[str]]:
    payload = load("rxe_extension_surrogate")
    return {k.lower(): list(v) for k, v in (payload.get("ingredient_brand_index") or {}).items()}


def status() -> dict:
    man = load("MANIFEST")
    return {
        "data_dir": str(DATA_DIR),
        "version": man.get("version", "unknown"),
        "is_surrogate": True,
        "loaded_files": loaded_files(),
        "counts": {
            "micromesh_keys": len(micromesh()),
            "colloquial_ades": len(colloquial_ades()),
            "pharmaconer_substances": len(pharmaconer()),
            "rxe_brands": len(rxe_brands()),
        },
        "research_grounding": man.get("research_grounding", {}),
        "disclaimer": man.get("disclaimer", ""),
    }
