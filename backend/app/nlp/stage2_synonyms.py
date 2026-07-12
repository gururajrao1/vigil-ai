"""Stage 2 — Synonym registry matching.

Compresses overlapping naming variations onto a single canonical surface
before NER / MedDRA mapping (e.g. IBU / IBUPROFEN TABLETS → ibuprofen).
"""
from __future__ import annotations

from typing import Optional

from .stage1_sanitize import fold_key
from .event_collapse import collapse_event_surface, inflection_folds

# Keys are fold_key() results → canonical storage form
PRODUCT_SYNONYMS: dict[str, str] = {
    "COVID19": "covid-19 mrna vaccine",
    "COVID": "covid-19 mrna vaccine",
    "COVID19MRNAVACCINE": "covid-19 mrna vaccine",
    "COVID19VACCINE": "covid-19 mrna vaccine",
    "COVID19VACCINATION": "covid-19 mrna vaccine",
    "SARSCOV2": "covid-19 mrna vaccine",
    "SARSCOV2VACCINE": "covid-19 mrna vaccine",
    "CORONAVACCINE": "covid-19 mrna vaccine",
    "CORONAVIRUSVACCINE": "covid-19 mrna vaccine",
    "PFIZER": "covid-19 mrna vaccine",
    "PFIZERBIONTECH": "covid-19 mrna vaccine",
    "MODERNA": "covid-19 mrna vaccine",
    "COMIRNATY": "covid-19 mrna vaccine",
    "SPIKEVAX": "covid-19 mrna vaccine",
    "IBU": "ibuprofen",
    "IBUPROFEN": "ibuprofen",
    "IBUPROFENTABLET": "ibuprofen",
    "IBUPROFENTABLETS": "ibuprofen",
    "IBUPROFEN200MG": "ibuprofen",
    "ADVIL": "ibuprofen",
    "MOTRIN": "ibuprofen",
    "BRUFEN": "ibuprofen",
    "NUROFEN": "ibuprofen",
    "TYLENOL": "acetaminophen",
    "PARACETAMOL": "paracetamol",
    "PARACETAMOLTABLETS": "paracetamol",
    "ACETAMINOPHEN": "acetaminophen",
    "ACETAMINOPHENTABLETS": "acetaminophen",
    "ASA": "aspirin",
    "ASPIRIN": "aspirin",
    "ASPIRINTABLETS": "aspirin",
    "PREDNISONE": "prednisone",
    "PREDNISONETABLETS": "prednisone",
}

REGION_SYNONYMS: dict[str, str] = {
    "USA": "United States",
    "US": "United States",
    "UNITEDSTATESOFAMERICA": "United States",
    "UK": "United Kingdom",
    "GB": "United Kingdom",
    "GREATBRITAIN": "United Kingdom",
    "UAE": "United Arab Emirates",
}

EVENT_SYNONYMS: dict[str, str] = {
    "BRAINZAPS": "paraesthesia",
    "BRAINZAP": "paraesthesia",
    "HEADSNAPS": "paraesthesia",
    "HEADSNAP": "paraesthesia",
    "BRAINFOG": "cognitive disorder",
    "STOMACHACHE": "abdominal pain",
    "STOMACHPAIN": "abdominal pain",
    "HEARTBURN": "dyspepsia",
    "ACIDREFLUX": "gastrooesophageal reflux disease",
    "DIZZYSPELLS": "dizziness",
    "RINGINGINEARS": "tinnitus",
    "SUICIDALTHOUGHTS": "suicidal ideation",
    "PANICATTACKS": "panic attack",
    "WEIGHTGAIN": "weight increased",
    "WEIGHTLOSS": "weight decreased",
    "HAIRLOSS": "alopecia",
    "DRYMOUTH": "dry mouth",
    "SHORTNESSOFBREATH": "dyspnoea",
    "SOB": "dyspnoea",
    "ALLER": "allergy",
    "ALLERGY": "allergy",
    "ALLERGIES": "allergy",
    "ALLERGIC": "allergy",
    "ALLERGICREACTION": "allergy",
    "ADVERSE": "adverse drug reaction",
    "ADR": "adverse drug reaction",
    "ADRS": "adverse drug reaction",
    "ADVERSEDRUGREACTION": "adverse drug reaction",
    "ADVERSEDRUGREACTIONS": "adverse drug reaction",
    "ADVERSEREACTION": "adverse drug reaction",
    "ADVERSEREACTIONS": "adverse drug reaction",
    "ADVERSESIDEEFFECT": "adverse drug reaction",
    "ADVERSESIDEEFFECTS": "adverse drug reaction",
    "ADVERSEEFFECT": "adverse drug reaction",
    "ADVERSEEFFECTS": "adverse drug reaction",
    "SIDEEFFECT": "adverse drug reaction",
    "SIDEEFFECTS": "adverse drug reaction",
    # Common patient / NER variants → lexicon surfaces
    "FAINT": "syncope",
    "FAINTED": "syncope",
    "FAINTING": "syncope",
    "LIGHTHEADED": "dizziness",
    "LIGHTHEADEDNESS": "dizziness",
    "DEPRESSED": "depression",
    "EXHAUSTED": "fatigue",
    "SWEATY": "sweating",
    "SWEATS": "sweating",
    "PUFFYFACE": "swollen face",
    "HEARTPALPITATIONS": "palpitations",
    "BURNINGSENSATION": "paresthesia",
    "FEBRILE": "fever",
    "FEBRIL": "fever",
    "ANGIOEDEMA": "angioedema",
    "DIA": "diarrhea",
    "DIARR": "diarrhea",
    "PAR": "paraesthesia",
    "PAL": "palpitations",
    "MIG": "migraine",
    "NUMB": "numbness",
}

_DOSAGE_FORM_RE_KEYS = (
    "TABLETS", "TABLET", "CAPSULS", "CAPSULES", "CAPSULE", "MG", "MCG", "ML",
    "INJECTION", "INJECTIONS", "SOLUTION", "SUSPENSION", "CREAM", "GEL",
)


def _strip_dosage_form(key: str) -> str:
    """IBUPROFENTABLETS / IBUPROFEN200MG → IBUPROFEN when exact key missing."""
    out = key
    for suffix in _DOSAGE_FORM_RE_KEYS:
        if out.endswith(suffix) and len(out) > len(suffix) + 2:
            out = out[: -len(suffix)]
            break
    # Trailing numeric strength (200MG already handled; bare 200)
    while out and out[-1].isdigit():
        out = out[:-1]
    return out


def lookup_product_synonym(value: str) -> Optional[str]:
    key = fold_key(value)
    if not key:
        return None
    if key in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[key]
    stripped = _strip_dosage_form(key)
    if stripped in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[stripped]
    if stripped in REGION_SYNONYMS:
        return REGION_SYNONYMS[stripped]
    return None


def lookup_event_synonym(value: str) -> Optional[str]:
    key = fold_key(value)
    if not key:
        return None
    # Exact + plural/singular fold variants
    for variant in inflection_folds(key):
        hit = EVENT_SYNONYMS.get(variant) or PRODUCT_SYNONYMS.get(variant)
        if hit:
            return hit
    # Cluster / token-set collapse (ADR family, allergy plurals, …)
    collapsed = collapse_event_surface(value)
    if collapsed:
        return collapsed
    return None


def lookup_region_synonym(value: str) -> Optional[str]:
    key = fold_key(value)
    return REGION_SYNONYMS.get(key) if key else None


def resolve_synonym(value: str, *, kind: str = "generic") -> Optional[str]:
    if kind == "product":
        return lookup_product_synonym(value)
    if kind == "event":
        return lookup_event_synonym(value)
    if kind == "region":
        return lookup_region_synonym(value)
    return lookup_product_synonym(value) or lookup_event_synonym(value) or lookup_region_synonym(value)
