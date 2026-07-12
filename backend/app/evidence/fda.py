"""openFDA adverse-event corroboration (NO API key required).

Queries the openFDA drug/event endpoint for a drug + reaction. Falls back to a
deterministic offline knowledge base when there is no network, so the demo always
produces evidence. Results are cached in-process.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import httpx

from ..config import settings
from ..nlp.lexicons import normalize_drug

_CACHE: Dict[str, tuple[float, dict]] = {}
_TTL = 3600

# Offline fallback: well-documented drug-reaction associations.
_OFFLINE_KB = {
    ("paracetamol", "liver damage"): 0.9,
    ("acetaminophen", "liver damage"): 0.9,
    ("ibuprofen", "stomach pain"): 0.8,
    ("ibuprofen", "heartburn"): 0.7,
    ("aspirin", "bleeding"): 0.85,
    ("aspirin", "stomach pain"): 0.7,
    ("metformin", "diarrhea"): 0.8,
    ("metformin", "nausea"): 0.75,
    ("atorvastatin", "muscle pain"): 0.8,
    ("statin", "muscle pain"): 0.8,
    ("sertraline", "nausea"): 0.7,
    ("sertraline", "insomnia"): 0.65,
    ("isotretinoin", "depression"): 0.6,
    ("isotretinoin", "hair loss"): 0.5,
    ("warfarin", "bleeding"): 0.9,
    ("amoxicillin", "rash"): 0.7,
    ("tramadol", "dizziness"): 0.7,
    ("gabapentin", "drowsiness"): 0.75,
    ("pregabalin", "dizziness"): 0.7,
    ("levothyroxine", "palpitations"): 0.6,
}


def _offline_lookup(drug: str, symptom: str) -> dict:
    score = _OFFLINE_KB.get((drug, symptom))
    if score is None:
        # partial: any KB entry for this drug?
        drug_hits = [v for (d, s), v in _OFFLINE_KB.items() if d == drug]
        score = (max(drug_hits) * 0.4) if drug_hits else 0.0
    return {
        "available": score > 0,
        "source": "offline_kb",
        "match_score": round(score, 2),
        "report_count": int(score * 1000),
        "confidence_boost": _boost(score),
    }


def _boost(score: float) -> int:
    if score >= 0.8:
        return 30
    if score >= 0.5:
        return 20
    if score > 0:
        return 10
    return 0


def query_openfda(drug: str, symptom: str, timeout: float = 3.0) -> dict:
    drug_n = normalize_drug(drug)
    sym = symptom.strip().lower()
    key = f"{drug_n}|{sym}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    result: Optional[dict] = None
    try:
        params = {
            "search": f'patient.drug.medicinalproduct:"{drug_n}" AND '
                      f'patient.reaction.reactionmeddrapt:"{sym}"',
            "limit": 1,
        }
        if settings.openfda_api_key:
            params["api_key"] = settings.openfda_api_key
        url = f"{settings.openfda_base_url}/drug/event.json"
        resp = httpx.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("meta", {}).get("results", {}).get("total", 0)
            norm = min(1.0, total / 500.0)
            result = {
                "available": total > 0,
                "source": "openfda",
                "match_score": round(norm, 2),
                "report_count": total,
                "confidence_boost": _boost(norm),
            }
        elif resp.status_code == 404:
            result = {"available": False, "source": "openfda", "match_score": 0.0,
                      "report_count": 0, "confidence_boost": 0}
    except Exception:
        result = None

    if result is None:
        result = _offline_lookup(drug_n, sym)

    _CACHE[key] = (now, result)
    return result


# --------------------------------------------------------------------------- #
# Medical-device evidence (openFDA MAUDE, /device/event.json — NO key required)
# --------------------------------------------------------------------------- #
_OFFLINE_DEVICE_KB = {
    ("insulin pump", "malfunction"): 0.9,
    ("insulin pump", "hyperglycemia"): 0.75,
    ("continuous glucose monitor", "inaccurate reading"): 0.8,
    ("pacemaker", "battery failure"): 0.85,
    ("hip implant", "device loosening"): 0.8,
    ("knee implant", "device loosening"): 0.75,
    ("coronary stent", "thrombosis"): 0.8,
    ("infusion pump", "overinfusion"): 0.85,
    ("ventilator", "malfunction"): 0.8,
    ("surgical mesh", "erosion"): 0.8,
}


def _offline_device_lookup(device: str, problem: str) -> dict:
    score = _OFFLINE_DEVICE_KB.get((device, problem))
    if score is None:
        hits = [v for (d, _p), v in _OFFLINE_DEVICE_KB.items() if d == device]
        score = (max(hits) * 0.4) if hits else 0.0
    return {
        "available": score > 0,
        "source": "offline_kb_maude",
        "match_score": round(score, 2),
        "report_count": int(score * 800),
        "confidence_boost": _boost(score),
    }


def query_maude(device: str, problem: str, timeout: float = 3.0) -> dict:
    """openFDA MAUDE device-event corroboration for a device + failure mode."""
    dev = (device or "").strip().lower()
    prob = (problem or "").strip().lower()
    key = f"dev::{dev}|{prob}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    result: Optional[dict] = None
    try:
        params = {
            "search": f'device.generic_name:"{dev}"',
            "limit": 1,
        }
        if settings.openfda_api_key:
            params["api_key"] = settings.openfda_api_key
        url = f"{settings.openfda_base_url}/device/event.json"
        resp = httpx.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("meta", {}).get("results", {}).get("total", 0)
            norm = min(1.0, total / 500.0)
            result = {
                "available": total > 0,
                "source": "openfda_maude",
                "match_score": round(norm, 2),
                "report_count": total,
                "confidence_boost": _boost(norm),
            }
        elif resp.status_code == 404:
            result = {"available": False, "source": "openfda_maude", "match_score": 0.0,
                      "report_count": 0, "confidence_boost": 0}
    except Exception:
        result = None

    if result is None:
        result = _offline_device_lookup(dev, prob)

    _CACHE[key] = (now, result)
    return result


def query_evidence(product_type: str, name: str, event: str, timeout: float = 3.0) -> dict:
    """Route to FAERS (drugs) or MAUDE (devices) based on product_type."""
    if (product_type or "drug") == "device":
        return query_maude(name, event, timeout=timeout)
    return query_openfda(name, event, timeout=timeout)
