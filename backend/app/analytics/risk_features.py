"""Feature extraction for proactive risk stratification.

Derives demographics, comorbidity vectors (UMLS-style CUI surrogates), and
severity ordinals from AE corpus text + NLP entities — offline, no API keys.

Wound / chronic-care cues (diabetic foot ulcer, necrosis, skin erosion) support
Syn3DWound / AZH-style comorbidity tagging in narrative data without requiring
the imaging datasets at runtime.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Age: "34F", "34 yo", "45-year-old", "aged 60", "I'm 27"
_COMORBIDITY_MAP: Dict[str, Tuple[str, str]] = {
    # surface → (canonical label, surrogate CUI)
    "diabetes": ("diabetes mellitus", "CUI:C0011849"),
    "type 2 diabetes": ("type 2 diabetes mellitus", "CUI:C0011860"),
    "type 1 diabetes": ("type 1 diabetes mellitus", "CUI:C0011854"),
    "diabetic foot": ("diabetic foot", "CUI:C0206172"),
    "diabetic foot ulcer": ("diabetic foot ulcer", "CUI:C1456868"),
    "chronic wound": ("chronic wound", "CUI:C0877359"),
    "pressure ulcer": ("pressure ulcer", "CUI:C0011127"),
    "decubitus": ("pressure ulcer", "CUI:C0011127"),
    "wound infection": ("wound infection", "CUI:C0043250"),
    "necrosis": ("necrosis", "CUI:C0027540"),
    "tissue necrosis": ("tissue necrosis", "CUI:C0027540"),
    "skin erosion": ("skin erosion", "CUI:C0332461"),
    "ulcer": ("ulcer", "CUI:C0041582"),
    "hypertension": ("hypertension", "CUI:C0020538"),
    "heart failure": ("heart failure", "CUI:C0018801"),
    "renal failure": ("renal failure", "CUI:C0035078"),
    "kidney disease": ("chronic kidney disease", "CUI:C1561643"),
    "chronic kidney disease": ("chronic kidney disease", "CUI:C1561643"),
    "copd": ("COPD", "CUI:C0024117"),
    "asthma": ("asthma", "CUI:C0004096"),
    "cancer": ("malignant neoplasm", "CUI:C0006826"),
    "obesity": ("obesity", "CUI:C0028754"),
    "depression": ("depression", "CUI:C0011570"),
    "epilepsy": ("epilepsy", "CUI:C0014544"),
    "rheumatoid arthritis": ("rheumatoid arthritis", "CUI:C0003873"),
}

# Grade 3+ MedDRA-style severity lexicon (social / ICSR narrative proxy)
_SEVERE_CUES = re.compile(
    r"\b("
    r"hospitali[sz]ed|icu|intensive\s+care|emergency\s+room|\ber\b|ed\s+visit|"
    r"life[\s-]?threatening|fatal|died|death|mortality|"
    r"anaphylaxis|anaphylactic|sepsis|septic\s+shock|"
    r"necrosis|amputation|organ\s+failure|renal\s+failure|"
    r"respiratory\s+failure|cardiac\s+arrest|stroke|hemorrhage|haemorrhage|"
    r"grade\s*[345]|severe|critical|serious\s+adverse"
    r")\b",
    re.I,
)

_AGE_NUM = re.compile(
    r"(?:aged?\s+|i['’]?m\s+|i am\s+)?(\d{1,3})\s*(?:yo|y/o|yrs?|years?[\s-]*old|\s*[mf]\b)?",
    re.I,
)


def parse_age_years(text: str) -> Optional[float]:
    if not text:
        return None
    m = _AGE_NUM.search(text)
    if not m:
        return None
    try:
        age = float(m.group(1))
    except ValueError:
        return None
    if age < 1 or age > 120:
        return None
    return age


def age_bracket(age: Optional[float]) -> str:
    if age is None:
        return "UNKNOWN"
    if age < 18:
        return "PEDIATRIC"
    if age >= 65:
        return "GERIATRIC"
    return "ADULT"


def parse_sex(text: str) -> str:
    if not text:
        return "U"
    t = text.lower()
    # Compact clinical shorthand: 34F / 67M
    if re.search(r"\b\d{1,3}\s*f\b", t) or re.search(
        r"\b(female|woman|women|girl|mother|wife|pregnant)\b", t
    ):
        return "F"
    if re.search(r"\b\d{1,3}\s*m\b", t) or re.search(
        r"\b(male|man|men|boy|father|husband)\b", t
    ):
        return "M"
    return "U"


def extract_comorbidities(
    text: str, entities: Optional[dict] = None
) -> Tuple[List[str], List[str]]:
    """Return (canonical labels, surrogate CUIs)."""
    found: Dict[str, str] = {}
    blob = (text or "").lower()
    # Prefer longer surfaces first
    for surface in sorted(_COMORBIDITY_MAP.keys(), key=len, reverse=True):
        if surface in blob and _COMORBIDITY_MAP[surface][0] not in found:
            label, cui = _COMORBIDITY_MAP[surface]
            found[label] = cui
    for c in (entities or {}).get("conditions") or []:
        raw = (c.get("normalized") or c.get("text") or "").lower().strip()
        if not raw:
            continue
        if raw in _COMORBIDITY_MAP:
            label, cui = _COMORBIDITY_MAP[raw]
            found[label] = cui
        else:
            for surface, (label, cui) in _COMORBIDITY_MAP.items():
                if surface in raw or raw in surface:
                    found[label] = cui
                    break
            else:
                found.setdefault(raw, f"CUI:LOCAL:{raw[:24]}")
    labels = list(found.keys())
    cuis = [found[k] for k in labels]
    return labels, cuis


def severity_ordinal(text: str, events: Optional[List[str]] = None) -> Tuple[float, bool]:
    """0–1 severity proxy; severe_ae True when Grade 3+ cues or critical lexicon."""
    score = 0.0
    if text and _SEVERE_CUES.search(text):
        score = 0.85
    crit_events = {
        "anaphylaxis", "death", "necrosis", "sepsis", "stroke",
        "renal failure", "cardiac arrest", "amputation",
    }
    for e in events or []:
        el = (e or "").lower()
        if any(c in el for c in crit_events):
            score = max(score, 0.9)
    return round(min(score, 1.0), 3), score >= 0.7


def row_from_post(
    *,
    text: str,
    drugs: List[str],
    events: List[str],
    entities: Optional[dict] = None,
    region: Optional[str] = None,
    product_type: str = "drug",
    post_id: Optional[int] = None,
    focus_product: Optional[str] = None,
    focus_event: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one risk feature dict from a corpus post."""
    age = parse_age_years(text)
    comorb, cuis = extract_comorbidities(text, entities)
    sev, severe = severity_ordinal(text, events)
    product = (focus_product or (drugs[0] if drugs else "")).lower()
    others = [d for d in drugs if d.lower() != product]
    domain = "vaccine" if product_type == "vaccine" else (product_type or "drug")
    if any("pump" in d or "catheter" in d or "stent" in d or "device" in d for d in drugs):
        if domain == "drug" and product_type != "drug":
            domain = product_type
    return {
        "post_id": post_id,
        "product": product,
        "product_type": domain,
        "atc_or_gmdn": None,
        "age_years": age,
        "age_bracket": age_bracket(age),
        "sex": parse_sex(text),
        "region": region or "Global",
        "comorbidities": comorb,
        "comorbidity_cuis": cuis,
        "concomitant_meds": others[:8],
        "target_ae_pt": (focus_event or (events[0] if events else "")).lower(),
        "events": [e.lower() for e in events],
        "severity_score": sev,
        "severe_ae": severe,
        "text": text,
    }


def entities_from_processed(entities_json: Optional[str]) -> dict:
    try:
        return json.loads(entities_json or "{}") or {}
    except Exception:
        return {}
