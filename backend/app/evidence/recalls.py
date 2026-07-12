"""openFDA recall / enforcement connector — NO API key required.

Attaches real FDA recall history to a signal: drugs via /drug/enforcement.json,
devices via /device/enforcement.json. Returns the most-recent recall (class, reason,
date, firm) plus a total count. Cached per product; deterministic offline fallback.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import httpx

from ..config import settings
from ..nlp.lexicons import normalize_drug

_CACHE: Dict[str, tuple[float, dict]] = {}
_TTL = 6 * 3600


def _empty(source: str) -> dict:
    return {"available": False, "source": source, "count": 0, "latest": None}


def _fetch(endpoint: str, search: str, source: str, timeout: float) -> Optional[dict]:
    try:
        params = {"search": search, "limit": 1, "sort": "recall_initiation_date:desc"}
        if settings.openfda_api_key:
            params["api_key"] = settings.openfda_api_key
        resp = httpx.get(f"{settings.openfda_base_url}{endpoint}", params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("meta", {}).get("results", {}).get("total", 0)
            results = data.get("results", []) or []
            latest = None
            if results:
                r0 = results[0]
                date = r0.get("recall_initiation_date")
                if date and len(date) == 8:
                    date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
                latest = {
                    "date": date,
                    "classification": r0.get("classification"),
                    "reason": (r0.get("reason_for_recall") or "")[:280],
                    "firm": r0.get("recalling_firm"),
                    "status": r0.get("status"),
                }
            return {"available": total > 0, "source": source, "count": total, "latest": latest}
        if resp.status_code == 404:
            return _empty(source)
    except Exception:
        return None
    return None


def query_recalls(product_type: str, name: str, timeout: float = 3.0) -> dict:
    is_device = (product_type or "drug") == "device"
    name_n = (name or "").strip().lower() if is_device else normalize_drug(name)
    key = f"rc::{'dev' if is_device else 'drug'}::{name_n}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    if is_device:
        result = _fetch("/device/enforcement.json",
                        f'product_description:"{name_n}"', "openfda_device_recall", timeout)
    else:
        result = _fetch(
            "/drug/enforcement.json",
            f'openfda.generic_name:"{name_n}" openfda.brand_name:"{name_n}"',
            "openfda_drug_recall", timeout,
        )

    if result is None:
        result = _empty("openfda_recall_offline")

    _CACHE[key] = (now, result)
    return result
