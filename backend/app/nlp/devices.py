"""Medical-device vigilance lexicons + coding (worldwide, offline surrogate).

Devices are treated as "products" (like drugs) so the same 4-gate AE detector and
disproportionality engine apply. Device names map to a GMDN / FDA product-code
surrogate, and device failure modes map to IMDRF adverse-event terminology
(surrogate). None of these are the licensed real dictionaries — they are curated,
clearly-labeled open surrogates sufficient for the demo and offline use.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Device surface term (+ synonyms) -> canonical device name
DEVICE_TO_CANONICAL: Dict[str, str] = {
    "insulin pump": "insulin pump",
    "insulin patch pump": "insulin pump",
    "omnipod": "insulin pump",
    "cgm": "continuous glucose monitor",
    "continuous glucose monitor": "continuous glucose monitor",
    "dexcom": "continuous glucose monitor",
    "freestyle libre": "continuous glucose monitor",
    "pacemaker": "pacemaker",
    "icd": "implantable cardioverter defibrillator",
    "implantable cardioverter defibrillator": "implantable cardioverter defibrillator",
    "hip implant": "hip implant",
    "hip replacement": "hip implant",
    "knee implant": "knee implant",
    "knee replacement": "knee implant",
    "coronary stent": "coronary stent",
    "drug-eluting stent": "coronary stent",
    "stent": "coronary stent",
    "infusion pump": "infusion pump",
    "iv pump": "infusion pump",
    "ventilator": "ventilator",
    "cpap": "cpap machine",
    "cpap machine": "cpap machine",
    "surgical mesh": "surgical mesh",
    "hernia mesh": "surgical mesh",
    "breast implant": "breast implant",
    "iud": "intrauterine device",
    "intrauterine device": "intrauterine device",
    "catheter": "catheter",
}

# Canonical device -> (GMDN/FDA product-code surrogate, device class)
DEVICE_GMDN: Dict[str, dict] = {
    "insulin pump": {"gmdn": "GMDN-47017 / FDA-LZG", "class": "II"},
    "continuous glucose monitor": {"gmdn": "GMDN-56663 / FDA-QBJ", "class": "II"},
    "pacemaker": {"gmdn": "GMDN-35141 / FDA-DXY", "class": "III"},
    "implantable cardioverter defibrillator": {"gmdn": "GMDN-35304 / FDA-LWS", "class": "III"},
    "hip implant": {"gmdn": "GMDN-41768 / FDA-JDI", "class": "III"},
    "knee implant": {"gmdn": "GMDN-38504 / FDA-JWH", "class": "II"},
    "coronary stent": {"gmdn": "GMDN-35928 / FDA-NIQ", "class": "III"},
    "infusion pump": {"gmdn": "GMDN-13217 / FDA-FRN", "class": "II"},
    "ventilator": {"gmdn": "GMDN-34832 / FDA-CBK", "class": "II"},
    "cpap machine": {"gmdn": "GMDN-45816 / FDA-BZD", "class": "II"},
    "surgical mesh": {"gmdn": "GMDN-43843 / FDA-FTL", "class": "II"},
    "breast implant": {"gmdn": "GMDN-35211 / FDA-FTR", "class": "III"},
    "intrauterine device": {"gmdn": "GMDN-33645 / FDA-HMB", "class": "II"},
    "catheter": {"gmdn": "GMDN-47569 / FDA-OZP", "class": "II"},
}

# Device failure-mode surface term (+ synonyms) -> IMDRF-style adverse-event term
FAILURE_TO_IMDRF: Dict[str, dict] = {
    "malfunction": {"term": "Device malfunction", "code": "IMDRF-A01"},
    "stopped working": {"term": "Failure to deliver / non-operation", "code": "IMDRF-A0303"},
    "battery failure": {"term": "Battery problem", "code": "IMDRF-A1201"},
    "battery drained": {"term": "Battery problem", "code": "IMDRF-A1201"},
    "overinfusion": {"term": "Over-infusion", "code": "IMDRF-A0801"},
    "over-infusion": {"term": "Over-infusion", "code": "IMDRF-A0801"},
    "underinfusion": {"term": "Under-infusion", "code": "IMDRF-A0802"},
    "inaccurate reading": {"term": "Measurement/output error", "code": "IMDRF-A05"},
    "false reading": {"term": "Measurement/output error", "code": "IMDRF-A05"},
    "device loosening": {"term": "Loosening / migration of device", "code": "IMDRF-A1502"},
    "loosening": {"term": "Loosening / migration of device", "code": "IMDRF-A1502"},
    "fracture": {"term": "Material fracture / breakage", "code": "IMDRF-A0902"},
    "breakage": {"term": "Material fracture / breakage", "code": "IMDRF-A0902"},
    "thrombosis": {"term": "Device-associated thrombosis", "code": "IMDRF-E2401"},
    "erosion": {"term": "Erosion / migration into tissue", "code": "IMDRF-A1503"},
    "lead dislodgement": {"term": "Lead dislodgement", "code": "IMDRF-A1504"},
    "electric shock": {"term": "Unintended electrical output", "code": "IMDRF-A1104"},
    "leakage": {"term": "Leak", "code": "IMDRF-A0701"},
    "occlusion": {"term": "Occlusion / blockage", "code": "IMDRF-A0601"},
}

DEVICE_TERMS = set(DEVICE_TO_CANONICAL.keys())
FAILURE_TERMS = set(FAILURE_TO_IMDRF.keys())


def _matcher(terms) -> re.Pattern:
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in ordered) + r")\b", re.IGNORECASE)


_DEVICE_RE = _matcher(DEVICE_TERMS)
_FAILURE_RE = _matcher(FAILURE_TERMS)


def canonical_device(surface: str) -> str:
    return DEVICE_TO_CANONICAL.get(surface.strip().lower(), surface.strip().lower())


def device_meta(device: str, failure: str) -> dict:
    """Return {gmdn, class, imdrf, imdrf_term} for a device signal."""
    dev = canonical_device(device)
    g = DEVICE_GMDN.get(dev, {})
    fm = FAILURE_TO_IMDRF.get((failure or "").strip().lower(), {})
    return {
        "gmdn": g.get("gmdn"),
        "device_class": g.get("class"),
        "imdrf": fm.get("code"),
        "imdrf_term": fm.get("term"),
    }


def extract_devices(text: str) -> Dict[str, List[dict]]:
    """Return device 'products' and 'failure modes' found by lexicon matching.

    Products go into the drugs/products bucket; failure modes into symptoms, so the
    existing AE gates + disproportionality engine work unchanged.
    """
    products, failures = [], []
    for m in _DEVICE_RE.finditer(text):
        surface = m.group(0)
        canon = canonical_device(surface)
        meta = DEVICE_GMDN.get(canon, {})
        products.append({
            "text": surface,
            "normalized": canon,
            "generic": canon,
            "atc": None,
            "gmdn": meta.get("gmdn"),
            "device_class": meta.get("class"),
            "start": m.start(),
            "end": m.end(),
            "source": "device_lexicon",
            "is_device": True,
        })
    for m in _FAILURE_RE.finditer(text):
        surface = m.group(0)
        fm = FAILURE_TO_IMDRF.get(surface.strip().lower(), {})
        failures.append({
            "text": surface,
            "normalized": surface.strip().lower(),
            "pt": fm.get("term") or surface.title(),
            "soc": "Device / product issues",
            "soc_code": "IMDRF",
            "imdrf": fm.get("code"),
            "start": m.start(),
            "end": m.end(),
            "source": "device_lexicon",
            "is_device_failure": True,
        })
    return {"products": products, "failures": failures}
