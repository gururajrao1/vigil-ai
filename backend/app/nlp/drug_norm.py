"""Worldwide drug normalization.

Resolves a drug surface form (brand or misspelling, any region) to a canonical
generic name + WHO ATC class. Resolution order:

1. Offline brand->generic map + ATC table (instant, no network) — India + global.
2. RxNorm public API (NIH, no key) for anything the offline map misses.

Results are cached both in-process and (optionally) persisted, and every network
call degrades to the offline path so the app runs with no internet.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from ..config import settings
from .lexicons import BRAND_TO_GENERIC, DRUG_ATC, GENERIC_DRUGS, atc_for, normalize_drug

logger = logging.getLogger("vigilai.drugnorm")

_CACHE: Dict[str, dict] = {}
_LOCK = threading.Lock()


def _offline(surface: str) -> dict:
    generic = normalize_drug(surface)
    known = generic in GENERIC_DRUGS or generic in DRUG_ATC
    return {
        "surface": surface,
        "generic": generic,
        "atc": atc_for(generic),
        "rxcui": None,
        "source": "offline_map" if generic != surface.strip().lower() or known else "verbatim",
    }


def _rxnorm(surface: str) -> Optional[dict]:
    if not settings.use_rxnorm:
        return None
    try:
        import httpx

        base = settings.rxnorm_base_url
        # 1) approximate match -> rxcui
        r = httpx.get(f"{base}/approximateTerm.json",
                      params={"term": surface, "maxEntries": 1}, timeout=4.0)
        cands = r.json().get("approximateGroup", {}).get("candidate", []) if r.status_code == 200 else []
        if not cands:
            return None
        rxcui = cands[0].get("rxcui")
        if not rxcui:
            return None
        # 2) rxcui -> ingredient name (generic)
        generic = surface.strip().lower()
        r2 = httpx.get(f"{base}/rxcui/{rxcui}/related.json",
                       params={"tty": "IN"}, timeout=4.0)
        if r2.status_code == 200:
            groups = r2.json().get("relatedGroup", {}).get("conceptGroup", [])
            for g in groups:
                for c in g.get("conceptProperties", []) or []:
                    if c.get("name"):
                        generic = c["name"].strip().lower()
                        break
        return {
            "surface": surface,
            "generic": generic,
            "atc": atc_for(generic),
            "rxcui": rxcui,
            "source": "rxnorm",
        }
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("RxNorm lookup failed for %r: %s", surface, exc)
        return None


def normalize(surface: str) -> dict:
    """Return {surface, generic, atc, rxcui, source}. Never raises."""
    key = (surface or "").strip().lower()
    if not key:
        return {"surface": surface, "generic": "", "atc": None, "rxcui": None, "source": "empty"}
    if key in _CACHE:
        return _CACHE[key]

    result = _offline(surface)
    # Only reach out to RxNorm when the offline map couldn't confidently map it.
    if result["source"] == "verbatim" and result["generic"] not in GENERIC_DRUGS:
        online = _rxnorm(surface)
        if online:
            result = online

    with _LOCK:
        _CACHE[key] = result
    return result


def generic_of(surface: str) -> str:
    return normalize(surface)["generic"] or normalize_drug(surface)


# Fragments / class words that NER sometimes emits as "drugs"
_JUNK_PRODUCTS = frozenset({
    "anti", "ben", "benz", "drug", "drugs", "medicine", "medication", "meds",
    "pill", "pills", "tablet", "tablets", "dose", "booster", "vaccine",
    "antibiotics", "antihistamine", "antihistamines", "antidepressant",
    "anti - depressants", "antipsychotic drug",
})


def canonical_product(surface: str) -> Optional[str]:
    """Normalize a product mention to a KG-safe label, or None if not a product.

    Rejects symptom lexicon hits mis-tagged as drugs, ultra-short fragments, and
    class words. Accepts generics, brands→INN, vaccines, and devices.

    Offline-only (no RxNorm) so bulk signal/KG builds never block on the network.
    """
    from .devices import DEVICE_GMDN, DEVICE_TO_CANONICAL, canonical_device
    from .lexicons import SYMPTOMS
    from ..analytics.vaccine import is_vaccine

    raw = (surface or "").strip().lower()
    if not raw or len(raw) < 3:
        return None
    if raw in _JUNK_PRODUCTS:
        return None

    # Device first (insulin pump, stent, …)
    if raw in DEVICE_TO_CANONICAL or raw in DEVICE_GMDN:
        return canonical_device(raw)

    # Offline brand→generic only (never RxNorm here — KG rebuilds thousands of labels)
    info = _offline(raw)
    generic = (info.get("generic") or raw).strip().lower()
    if not generic or len(generic) < 3 or generic in _JUNK_PRODUCTS:
        return None

    # Symptom mis-tagged as drug (e.g. "acid reflux") — drop unless also a known product
    if generic in SYMPTOMS and generic not in GENERIC_DRUGS and generic not in DRUG_ATC:
        if not is_vaccine(generic):
            return None

    if (
        generic in GENERIC_DRUGS
        or generic in DRUG_ATC
        or info.get("source") == "offline_map"
        or is_vaccine(generic)
        or generic in DEVICE_TO_CANONICAL
        or generic in DEVICE_GMDN
    ):
        return generic

    # Keep longer verbatim product-like strings (novel mentions) but not symptom PTs
    if generic in SYMPTOMS:
        return None
    if " " in generic or len(generic) >= 6:
        return generic
    return None
