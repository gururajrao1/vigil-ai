"""Medical-device vigilance lexicons + coding (worldwide, offline surrogate).

Devices are treated as "products" (like drugs) so the same 4-gate AE detector and
disproportionality engine apply. Device names map to a GMDN / FDA product-code
surrogate, and device failure modes map to IMDRF adverse-event terminology
(surrogate). None of these are the licensed real dictionaries — they are curated,
clearly-labeled open surrogates sufficient for the demo and offline use.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

# Device surface term (+ synonyms) -> canonical device name
DEVICE_TO_CANONICAL: Dict[str, str] = {
    # Glucose monitoring / insulin delivery
    "insulin pump": "insulin pump",
    "insulin patch pump": "insulin pump",
    "omnipod": "insulin pump",
    "minimed": "insulin pump",
    "mini med": "insulin pump",
    "medtronic pump": "insulin pump",
    "tandem tslim": "insulin pump",
    "tslim": "insulin pump",
    "cgm": "continuous glucose monitor",
    "continuous glucose monitor": "continuous glucose monitor",
    "glucose monitor": "continuous glucose monitor",
    "blood glucose monitor": "blood glucose meter",
    "blood glucose meter": "blood glucose meter",
    "glucose meter": "blood glucose meter",
    "glucometer": "blood glucose meter",
    "dexcom": "continuous glucose monitor",
    "freestyle libre": "continuous glucose monitor",
    "libre": "continuous glucose monitor",
    "guardian sensor": "continuous glucose monitor",
    "guardian4": "continuous glucose monitor",
    "guardian 4": "continuous glucose monitor",
    # Cardiac rhythm
    "pacemaker": "pacemaker",
    "icd": "implantable cardioverter defibrillator",
    "implantable cardioverter defibrillator": "implantable cardioverter defibrillator",
    "defibrillator": "implantable cardioverter defibrillator",
    # Orthopedic
    "hip implant": "hip implant",
    "hip replacement": "hip implant",
    "knee implant": "knee implant",
    "knee replacement": "knee implant",
    # Vascular / implantables
    "coronary stent": "coronary stent",
    "drug-eluting stent": "coronary stent",
    "stent": "coronary stent",
    "breast implant": "breast implant",
    "surgical mesh": "surgical mesh",
    "hernia mesh": "surgical mesh",
    "iud": "intrauterine device",
    "intrauterine device": "intrauterine device",
    "intrauterine system": "intrauterine device",
    "mirena": "intrauterine device",
    "catheter": "catheter",
    "foley catheter": "catheter",
    "urinary catheter": "catheter",
    # Infusion / respiratory
    "infusion pump": "infusion pump",
    "iv pump": "infusion pump",
    "ventilator": "ventilator",
    "cpap": "cpap machine",
    "cpap machine": "cpap machine",
    "bipap": "cpap machine",
    "dreamstation": "cpap machine",
    "respironics": "cpap machine",
    # Other common demo devices
    "dialysis machine": "dialysis machine",
    "hemodialysis machine": "dialysis machine",
    "prosthetic knee": "knee implant",
    "cochlear implant": "cochlear implant",
    "insulin pen": "insulin pen",
}

# Brand / model fragments frequently seen in MAUDE titles (contains-match on lowercase)
BRAND_MODEL_TO_DEVICE: Dict[str, str] = {
    "minimed": "insulin pump",
    "780g": "insulin pump",
    "670g": "insulin pump",
    "640g": "insulin pump",
    "mmt-": "insulin pump",
    "omnipod": "insulin pump",
    "tslim": "insulin pump",
    "tandem": "insulin pump",
    "guardian": "continuous glucose monitor",
    "dexcom": "continuous glucose monitor",
    "libre": "continuous glucose monitor",
    "freestyle": "continuous glucose monitor",
    "dreamstation": "cpap machine",
    "respironics": "cpap machine",
    "airsense": "cpap machine",
    "resmed": "cpap machine",
    "evis eus": "endoscope",
    "bronchofiber": "endoscope",
    "inset ii": "infusion pump",
    "pacemaker": "pacemaker",
}

# Canonical device -> (GMDN/FDA product-code surrogate, device class)
DEVICE_GMDN: Dict[str, dict] = {
    "insulin pump": {"gmdn": "GMDN-47017 / FDA-LZG", "class": "II"},
    "continuous glucose monitor": {"gmdn": "GMDN-56663 / FDA-QBJ", "class": "II"},
    "blood glucose meter": {"gmdn": "GMDN-35271 / FDA-NBW", "class": "II"},
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
    "dialysis machine": {"gmdn": "GMDN-11218 / FDA-FKR", "class": "II"},
    "cochlear implant": {"gmdn": "GMDN-36067 / FDA-MCM", "class": "III"},
    "insulin pen": {"gmdn": "GMDN-45604 / FDA-NSD", "class": "II"},
    "endoscope": {"gmdn": "GMDN-35259 / FDA-NGB", "class": "II"},
}

FAILURE_TO_IMDRF: Dict[str, dict] = {
    "malfunction": {"term": "Device malfunction", "code": "IMDRF-A01"},
    "device malfunction": {"term": "Device malfunction", "code": "IMDRF-A01"},
    "stopped working": {"term": "Failure to deliver / non-operation", "code": "IMDRF-A0303"},
    "failure to deliver": {"term": "Failure to deliver / non-operation", "code": "IMDRF-A0303"},
    "battery failure": {"term": "Battery problem", "code": "IMDRF-A1201"},
    "battery drained": {"term": "Battery problem", "code": "IMDRF-A1201"},
    "overinfusion": {"term": "Over-infusion", "code": "IMDRF-A0801"},
    "over-infusion": {"term": "Over-infusion", "code": "IMDRF-A0801"},
    "underinfusion": {"term": "Under-infusion", "code": "IMDRF-A0802"},
    "under-infusion": {"term": "Under-infusion", "code": "IMDRF-A0802"},
    "inaccurate reading": {"term": "Measurement/output error", "code": "IMDRF-A05"},
    "false reading": {"term": "Measurement/output error", "code": "IMDRF-A05"},
    "inaccurate": {"term": "Measurement/output error", "code": "IMDRF-A05"},
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
    "injury": {"term": "Patient injury associated with device", "code": "IMDRF-E01"},
    "adverse event": {"term": "Device-related adverse event", "code": "IMDRF-E00"},
    "rupture": {"term": "Material rupture / breakage", "code": "IMDRF-A0903"},
}

AMBIGUOUS_BARE_PRODUCTS: Set[str] = {
    "glucose", "insulin", "libre", "guardian", "tandem", "stent",
}

DEVICE_TERMS = set(DEVICE_TO_CANONICAL.keys())
FAILURE_TERMS = set(FAILURE_TO_IMDRF.keys())


def _matcher(terms) -> re.Pattern:
    ordered = sorted(terms, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in ordered) + r")\b", re.IGNORECASE)


_DEVICE_RE = _matcher(DEVICE_TERMS)
_FAILURE_RE = _matcher(FAILURE_TERMS)


def canonical_device(surface: str) -> str:
    key = (surface or "").strip().lower()
    if key in DEVICE_TO_CANONICAL:
        return DEVICE_TO_CANONICAL[key]
    if key in DEVICE_GMDN:
        return key
    if key in BRAND_MODEL_TO_DEVICE:
        return BRAND_MODEL_TO_DEVICE[key]
    return key


def is_known_device(name: str) -> bool:
    key = (name or "").strip().lower()
    if not key:
        return False
    if key in DEVICE_GMDN or key in DEVICE_TO_CANONICAL:
        return True
    mapped = DEVICE_TO_CANONICAL.get(key) or BRAND_MODEL_TO_DEVICE.get(key)
    return bool(mapped and (mapped in DEVICE_GMDN or mapped in DEVICE_TO_CANONICAL.values()))


def resolve_brand_to_device(text: str) -> Optional[str]:
    low = (text or "").lower()
    for frag, canon in sorted(BRAND_MODEL_TO_DEVICE.items(), key=lambda kv: -len(kv[0])):
        if frag in low:
            return canon
    return None


def device_meta(device: str, failure: str) -> dict:
    dev = canonical_device(device)
    g = DEVICE_GMDN.get(dev, {})
    fm = FAILURE_TO_IMDRF.get((failure or "").strip().lower(), {})
    if not fm and failure:
        # try PT-style lowercase
        for k, v in FAILURE_TO_IMDRF.items():
            if (v.get("term") or "").lower() == (failure or "").strip().lower():
                fm = v
                break
    return {
        "gmdn": g.get("gmdn"),
        "device_class": g.get("class"),
        "imdrf": fm.get("code"),
        "imdrf_term": fm.get("term"),
    }


def _product_dict(surface: str, canon: str, start: int, end: int, source: str) -> dict:
    meta = DEVICE_GMDN.get(canon, {})
    return {
        "text": surface,
        "normalized": canon,
        "generic": canon,
        "atc": None,
        "gmdn": meta.get("gmdn"),
        "device_class": meta.get("class"),
        "start": start,
        "end": end,
        "source": source,
        "is_device": True,
        "product_type": "device",
    }


def extract_devices(text: str) -> Dict[str, List[dict]]:
    """Return device products + failure modes (lexicon + brand/model map)."""
    products, failures = [], []
    seen_canon: Set[str] = set()
    blob = text or ""

    for m in _DEVICE_RE.finditer(blob):
        surface = m.group(0)
        canon = canonical_device(surface)
        if canon in seen_canon:
            continue
        seen_canon.add(canon)
        products.append(_product_dict(surface, canon, m.start(), m.end(), "device_lexicon"))

    brand = resolve_brand_to_device(blob)
    if brand and brand not in seen_canon:
        products.append(
            _product_dict(brand, brand, 0, min(len(blob), len(brand)), "device_brand_map")
        )
        seen_canon.add(brand)

    for m in _FAILURE_RE.finditer(blob):
        surface = m.group(0)
        fm = FAILURE_TO_IMDRF.get(surface.strip().lower(), {})
        failures.append({
            "text": surface,
            "normalized": (fm.get("term") or surface).strip().lower(),
            "pt": fm.get("term") or surface.title(),
            "soc": "Device / product issues",
            "soc_code": "IMDRF",
            "imdrf": fm.get("code"),
            "start": m.start(),
            "end": m.end(),
            "source": "device_lexicon",
            "is_device_failure": True,
        })

    low = blob.lower()
    if products and not failures and any(
        k in low for k in ("malfunction", "mdr", "device report", "injury", "failure", "adverse")
    ):
        fm = FAILURE_TO_IMDRF["malfunction"]
        failures.append({
            "text": "malfunction",
            "normalized": fm["term"].lower(),
            "pt": fm["term"],
            "soc": "Device / product issues",
            "soc_code": "IMDRF",
            "imdrf": fm["code"],
            "start": 0,
            "end": 11,
            "source": "device_inferred_failure",
            "is_device_failure": True,
        })

    return {"products": products, "failures": failures}
