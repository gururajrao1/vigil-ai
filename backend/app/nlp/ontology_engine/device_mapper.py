"""Device verbatim / FDA product code / malfunction → GMDN + EMDN + risk class.

Canonicalisation reuses ``app.nlp.devices`` (trade-name and brand/model tables) and
layers the EU EMDN parallel code, the MDR risk class, the SaMD flag, and the IMDRF
failure-mode crosswalk on top.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

from ..devices import (
    BRAND_MODEL_TO_DEVICE,
    DEVICE_GMDN,
    DEVICE_TO_CANONICAL,
    FAILURE_TO_IMDRF,
    canonical_device,
)
from . import crosswalk, dictionary_store
from .models import AuditStamp, DeviceMap

_SAMD_INDEX: Dict[str, Tuple[str, dict]] = {}
_FDA_CODE_INDEX: Dict[str, Tuple[str, dict]] = {}
_LOCK = threading.Lock()
_READY = False


def _clean(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _build_index() -> None:
    global _READY
    if _READY:
        return
    with _LOCK:
        if _READY:
            return
        for name, row in dictionary_store.samd_table().items():
            _SAMD_INDEX[_clean(name)] = (name, row)
            for alias in row.get("aliases") or []:
                _SAMD_INDEX.setdefault(_clean(alias), (name, row))
        for name, row in dictionary_store.device_table().items():
            code = _clean(row.get("fda_product_code"))
            if code:
                _FDA_CODE_INDEX.setdefault(code, (name, row))
        _READY = True


def reload_index() -> None:
    global _READY
    with _LOCK:
        _SAMD_INDEX.clear()
        _FDA_CODE_INDEX.clear()
        _READY = False


def _audit() -> AuditStamp:
    return AuditStamp(
        source="gmdn_emdn_surrogate",
        dictionaries=["gmdn_emdn_surrogate.json", "app.nlp.devices"],
    )


def is_known_device(term: str) -> bool:
    _build_index()
    key = _clean(term)
    if not key:
        return False
    if key in _SAMD_INDEX or key in _FDA_CODE_INDEX:
        return True
    if key in DEVICE_TO_CANONICAL or key in DEVICE_GMDN or key in BRAND_MODEL_TO_DEVICE:
        return True
    return canonical_device(key) in dictionary_store.device_table()


def imdrf_for(failure: str) -> Dict[str, Optional[str]]:
    key = _clean(failure)
    if not key:
        return {}
    hit = FAILURE_TO_IMDRF.get(key)
    if not hit:
        for row in FAILURE_TO_IMDRF.values():
            if _clean(row.get("term")) == key:
                hit = row
                break
    if not hit:
        for term, row in FAILURE_TO_IMDRF.items():
            if term in key:
                hit = row
                break
    return {"imdrf_code": hit.get("code"), "imdrf_term": hit.get("term")} if hit else {}


def map_device(verbatim: str, failure: str = "") -> DeviceMap:
    """Resolve a device surface (trade name, category, FDA code, or SaMD term)."""
    _build_index()
    audit = _audit()
    key = _clean(verbatim)
    imdrf = imdrf_for(failure)

    if not key:
        return DeviceMap(verbatim=verbatim or "", matched=False,
                         match_method="empty", audit=audit, **imdrf)

    table = dictionary_store.device_table()
    row: Optional[dict] = None
    canonical: Optional[str] = None
    method = "unmatched"

    if key in _SAMD_INDEX:
        canonical, row = _SAMD_INDEX[key]
        method = "samd_lexicon"
    elif key in _FDA_CODE_INDEX:
        canonical, row = _FDA_CODE_INDEX[key]
        method = "fda_product_code"
    else:
        candidate = canonical_device(key)
        if candidate in table:
            canonical, row = candidate, table[candidate]
            method = "device_lexicon" if candidate == key else "brand_or_synonym_map"
        else:
            for name, samd_row in _SAMD_INDEX.items():
                if len(name) >= 6 and name in key:
                    canonical, row = samd_row[0], samd_row[1]
                    method = "samd_substring"
                    break

    if row is None or canonical is None:
        return DeviceMap(
            verbatim=verbatim,
            canonical_device=canonical_device(key) or None,
            cui=crosswalk.cui_for("device", key),
            matched=False,
            match_method="unmatched",
            audit=audit,
            **imdrf,
        )

    cross = crosswalk.crosswalk_row("device", canonical)
    return DeviceMap(
        verbatim=verbatim,
        canonical_device=canonical,
        gmdn_code=row.get("gmdn_code") or cross.get("gmdn"),
        gmdn_term=row.get("gmdn_term"),
        fda_product_code=row.get("fda_product_code"),
        emdn_code=row.get("emdn_code") or cross.get("emdn"),
        emdn_term=row.get("emdn_term"),
        fda_class=row.get("fda_class"),
        eu_mdr_class=row.get("eu_mdr_class"),
        is_samd=bool(row.get("is_samd")),
        implantable=bool(row.get("implantable")),
        cui=cross.get("cui"),
        matched=True,
        match_method=method,
        audit=audit,
        **imdrf,
    )
