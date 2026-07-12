"""Indication / condition normalization (separate from adverse-event PTs).

Condition = why the patient is treated (diagnosis / indication).
Symptom/AE = what went wrong after exposure (used in disproportionality).

Only known clinical indications survive; transformer debris (browser, battery,
arms, 155) is dropped. Synonyms collapse (allergy/allergies, covid/covid-19).
"""
from __future__ import annotations

from typing import Optional

from .event_collapse import inflection_folds
from .lexicons import CONDITIONS
from .stage1_sanitize import fold_key, sanitize_surface
from .term_glossary import is_nonclinical_surface

# fold_key → canonical indication label (lowercase)
_CONDITION_SYNONYMS: dict[str, str] = {
    "ALLERGIES": "allergy",
    "ALLERGY": "allergy",
    "COVID": "covid-19",
    "COVID19": "covid-19",
    "CORONA": "covid-19",
    "CORONAVIRUS": "covid-19",
    "FLU": "influenza",
    "INFLUENZA": "influenza",
    "HIGHBLOODPRESSURE": "hypertension",
    "HYPERTENSION": "hypertension",
    "HIGHCHOLESTEROL": "high cholesterol",
    "TYPE2DIABETES": "type 2 diabetes",
    "TYPE1DIABETES": "type 1 diabetes",
    "DIABETESMELLITUSTYPE2": "type 2 diabetes",
    "DIABETESMELLITUSTYPE1": "type 1 diabetes",
    "2DIABETES": "type 2 diabetes",
    "T2DM": "type 2 diabetes",
    "T1DM": "type 1 diabetes",
    "DM2": "type 2 diabetes",
    "ACIDREFLUX": "gerd",
    "GERD": "gerd",
    "GASTROESOPHAGEALREFLUX": "gerd",
    "GASTROOESOPHAGEALREFLUXDISEASE": "gerd",
    "UTI": "urinary tract infection",
    "URINARYTRACTINFECTION": "urinary tract infection",
    "RA": "rheumatoid arthritis",
    "RHEUMATOIDARTHRITIS": "rheumatoid arthritis",
    "OA": "osteoarthritis",
    "OSTEOARTHRITIS": "osteoarthritis",
    "CKD": "chronic kidney disease",
    "CHRONICKIDNEYDISEASE": "chronic kidney disease",
    "CAD": "coronary artery disease",
    "CORONARYARTERYDISEASE": "coronary artery disease",
    "CHF": "heart failure",
    "HEARTFAILURE": "heart failure",
    "AF": "atrial fibrillation",
    "AFIB": "atrial fibrillation",
    "ATRIALFIBRILLATION": "atrial fibrillation",
    "DVT": "deep vein thrombosis",
    "DEEPVEINTHROMBOSIS": "deep vein thrombosis",
    "COMMONCOLD": "common cold",
    "COLD": "common cold",
    "ACNEVULGARIS": "acne",
    "ACNE": "acne",
    "SEIZUREDISORDER": "epilepsy",
    "EPILEPSY": "epilepsy",
    "CROHNSDISEASE": "crohn's disease",
    "CROHNS": "crohn's disease",
    "ULCERATIVECOLITIS": "ulcerative colitis",
    "UC": "ulcerative colitis",
    "BPH": "enlarged prostate",
    "ENLARGEDPROSTATE": "enlarged prostate",
    "ED": "erectile dysfunction",
    "ERECTILEDYSFUNCTION": "erectile dysfunction",
}

# Body parts / device / UI debris that NER dumps into "conditions"
_CONDITION_JUNK = frozenset({
    "155", "arms", "back", "battery", "battery failure", "biologic", "biopsy",
    "blood", "blood work", "bone", "bones", "bow", "bowel", "browser", "cause",
    "chemistry", "chest", "cho", "ecg", "gin", "gui", "gum", "hem", "int",
    "iso", "lip", "mca", "mid", "per", "pit", "pts", "related enterocolitis",
    "- related enterocolitis", "apples of my cheeks", "bone density / vitamin d",
    "continuous glucose monitor",
})

_SHORT_CONDITION_OK = frozenset({
    "flu", "hiv", "ibs", "uti", "dvt", "ocd", "adhd", "ptsd", "copd", "gerd",
    "pcos", "acne", "gout", "cold", "af",
})


def _canonical_label(value: str) -> str:
    """Stable lowercase indication label; keep known acronyms styled."""
    # Preserve apostrophes in clinical names (Crohn's, Bell's)
    raw = (value or "").strip()
    raw = raw.replace("\u2019", "'")
    # Soft sanitize: collapse space, keep apostrophe
    import re
    raw = re.sub(r"\s+", " ", raw).strip(" -")
    s = raw.lower()
    if not s:
        return ""
    # Repair sanitize damage: "crohn s" → "crohn's"
    s = s.replace("crohn s ", "crohn's ").replace("crohn s", "crohn's")
    s = s.replace("bell s ", "bell's ").replace("bell s", "bell's")
    acronyms = {
        "hiv": "HIV", "ibs": "IBS", "uti": "UTI", "dvt": "DVT", "ocd": "OCD",
        "adhd": "ADHD", "ptsd": "PTSD", "copd": "COPD", "gerd": "GERD",
        "pcos": "PCOS", "covid-19": "COVID-19", "covid19": "COVID-19",
    }
    if s in acronyms:
        return acronyms[s]
    return s


def canonical_condition(surface: str) -> Optional[str]:
    """Return one canonical indication label, or None if junk / unknown."""
    san = sanitize_surface(surface)
    if not san.cleaned:
        return None
    low = san.cleaned.lower().lstrip("- ").strip()
    if not low:
        return None
    if low in _CONDITION_JUNK or is_nonclinical_surface(low):
        return None
    if len(low) < 3:
        return None
    if len(low) < 4 and low not in _SHORT_CONDITION_OK and fold_key(low) not in {
        fold_key(x) for x in _SHORT_CONDITION_OK
    }:
        return None

    # Synonym collapse
    for variant in inflection_folds(fold_key(low)):
        syn = _CONDITION_SYNONYMS.get(variant)
        if syn:
            low = syn
            break

    # Exact lexicon hit
    if low in CONDITIONS:
        return _canonical_label(low)

    # Fuzzy against CONDITIONS catalog (RapidFuzz / Jaccard)
    hit = _fuzzy_condition(low)
    if hit:
        return _canonical_label(hit)

    return None


def _fuzzy_condition(query: str, threshold: float = 85.0) -> Optional[str]:
    try:
        from rapidfuzz import fuzz, process  # type: ignore

        choices = sorted(CONDITIONS, key=len, reverse=True)
        match = process.extractOne(
            query,
            choices,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )
        if match:
            return match[0]
    except Exception:
        pass
    # Token Jaccard fallback
    q = set(query.replace("-", " ").split())
    best, best_s = None, 0.0
    for c in CONDITIONS:
        t = set(c.replace("-", " ").split())
        if not t:
            continue
        score = len(q & t) / len(q | t)
        if score > best_s:
            best, best_s = c, score
    if best and best_s >= 0.85:
        return best
    return None


def normalize_condition_label(value: str) -> str:
    return canonical_condition(value) or ""
