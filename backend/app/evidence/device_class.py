"""openFDA device classification connector — NO API key required.

Resolves the REAL FDA product code, device class (1/2/3), and regulation number for
a device name via /device/classification.json. Used to upgrade the offline GMDN/FDA
surrogate to real FDA regulatory metadata when a match exists. Cached per device;
falls back cleanly (caller keeps the surrogate) when offline or unmatched.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import httpx

from ..config import settings
from ..nlp.devices import canonical_device

_CACHE: Dict[str, tuple[float, dict]] = {}
_TTL = 24 * 3600

_CLASS_MAP = {"1": "I", "2": "II", "3": "III"}


def query_device_classification(device: str, timeout: float = 3.0) -> dict:
    dev = canonical_device(device)
    key = f"dc::{dev}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    result: Optional[dict] = None
    try:
        params = {"search": f'device_name:"{dev}"', "limit": 1}
        if settings.openfda_api_key:
            params["api_key"] = settings.openfda_api_key
        resp = httpx.get(f"{settings.openfda_base_url}/device/classification.json",
                         params=params, timeout=timeout)
        if resp.status_code == 200:
            results = resp.json().get("results", []) or []
            if results:
                r0 = results[0]
                dc = str(r0.get("device_class", "")).strip()
                result = {
                    "available": True,
                    "source": "openfda_device_classification",
                    "product_code": r0.get("product_code"),
                    "device_class": _CLASS_MAP.get(dc, dc or None),
                    "regulation_number": r0.get("regulation_number"),
                    "device_name": r0.get("device_name"),
                    "medical_specialty": r0.get("medical_specialty_description"),
                }
            else:
                result = {"available": False, "source": "openfda_device_classification"}
        elif resp.status_code == 404:
            result = {"available": False, "source": "openfda_device_classification"}
    except Exception:
        result = None

    if result is None:
        result = {"available": False, "source": "device_classification_offline"}

    _CACHE[key] = (now, result)
    return result
