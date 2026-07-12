"""DailyMed (NLM) structured product label connector — NO API key required.

Confirms whether an FDA-approved Structured Product Label (SPL) exists for a drug
and returns the label title + a stable DailyMed link. This is real regulatory
label evidence (the "is this a label-listed product?" corroboration). Cached in
process; degrades to a deterministic offline result when there is no network.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import httpx

from ..config import settings
from ..nlp.lexicons import normalize_drug

_CACHE: Dict[str, tuple[float, dict]] = {}
_TTL = 6 * 3600

_SETID_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"

# Minimal offline knowledge base: well-known labelled products so the demo still
# shows label evidence with no network. (Not exhaustive — real data via the API.)
_OFFLINE = {
    "isotretinoin", "paracetamol", "acetaminophen", "ibuprofen", "aspirin",
    "metformin", "atorvastatin", "sertraline", "warfarin", "amoxicillin",
    "gabapentin", "pregabalin", "levothyroxine", "rivaroxaban", "semaglutide",
    "diclofenac", "paroxetine", "amoxicillin clavulanate",
}


def _offline(drug_n: str) -> dict:
    known = drug_n in _OFFLINE
    return {
        "available": known,
        "source": "dailymed_offline",
        "title": f"{drug_n.title()} (US prescribing information)" if known else None,
        "setid": None,
        "url": None,
        "label_count": 1 if known else 0,
    }


def query_dailymed(drug: str, timeout: float = 3.0) -> dict:
    """Look up an SPL for a drug by name. Cached by normalized drug name."""
    drug_n = normalize_drug(drug)
    key = f"dm::{drug_n}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    result: Optional[dict] = None
    try:
        url = f"{settings.dailymed_base_url}/spls.json"
        resp = httpx.get(url, params={"drug_name": drug_n, "pagesize": 1}, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            rows = data.get("data", []) or []
            total = data.get("metadata", {}).get("total_elements", len(rows))
            if rows:
                r0 = rows[0]
                setid = r0.get("setid")
                result = {
                    "available": True,
                    "source": "dailymed",
                    "title": r0.get("title"),
                    "setid": setid,
                    "url": _SETID_URL.format(setid=setid) if setid else None,
                    "label_count": total,
                }
            else:
                result = {"available": False, "source": "dailymed", "title": None,
                          "setid": None, "url": None, "label_count": 0}
    except Exception:
        result = None

    if result is None:
        result = _offline(drug_n)

    _CACHE[key] = (now, result)
    return result
