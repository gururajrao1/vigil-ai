"""Labeling-gap detection — classify each signal event against the drug's FDA label.

Novelty tiers:
  "novel"    — event / synonyms NOT found in the adverse_reactions or warnings
               section text AND NOT covered by our boxed-warning registry.
  "in_label" — event found in adverse_reactions or warnings section text.
  "boxed"    — event already covered by our boxed-warning registry (the
               boxed_match returned covers_event=True).
  "unknown"  — DailyMed unreachable AND event not in our offline synonym set
               for this drug — we cannot classify.

The function is intentionally deterministic and offline-first: all network calls
are wrapped with a graceful exception handler that falls back to the offline
classification path.
"""
from __future__ import annotations

import re
import time
from typing import Dict, Optional

import httpx

from ..config import settings
from ..nlp.lexicons import normalize_drug

# Process-level cache keyed on normalised drug name → (ts, section_text).
_SPL_CACHE: Dict[str, tuple[float, str]] = {}
_TTL = 6 * 3600  # 6 hours

# In-process setid cache to avoid duplicate /spls.json lookups when
# assess_label_gap is called many times for the same drug.
_SETID_CACHE: Dict[str, tuple[float, Optional[str]]] = {}

# ---------------------------------------------------------------------------
# Offline adverse-reaction synonym sets for the demo corpus drugs.
# Keys are generic drug names (normalised). Values are sets of lowercase terms
# known to appear in the adverse_reactions / warnings sections of the official
# label (a curated teaching subset — NOT the complete label text).
# ---------------------------------------------------------------------------
_OFFLINE_REACTIONS: Dict[str, set] = {
    "isotretinoin": {
        "cheilitis", "dry lips", "dry skin", "xeroderma", "conjunctivitis",
        "nosebleed", "epistaxis", "myalgia", "arthralgia", "elevated liver enzymes",
        "hyperlipidaemia", "triglycerides", "headache", "depression",
        "inflammatory bowel disease", "pseudotumor cerebri", "night blindness",
    },
    "ibuprofen": {
        "nausea", "dyspepsia", "abdominal pain", "diarrhoea", "constipation",
        "dizziness", "headache", "oedema", "hypertension", "rash",
        "gastrointestinal bleeding", "gi bleeding", "gastric ulcer",
        "renal impairment", "elevated blood pressure",
    },
    "diclofenac": {
        "nausea", "dyspepsia", "abdominal pain", "diarrhoea", "headache",
        "oedema", "hypertension", "rash", "gastrointestinal bleeding",
        "gi bleeding", "gastric ulcer", "renal impairment",
    },
    "paracetamol": {
        "hepatotoxicity", "liver damage", "liver failure", "rash", "nausea",
        "vomiting", "overdose",
    },
    "acetaminophen": {
        "hepatotoxicity", "liver damage", "liver failure", "rash", "nausea",
        "vomiting", "overdose",
    },
    "aspirin": {
        "nausea", "dyspepsia", "gastrointestinal bleeding", "gi bleeding",
        "tinnitus", "rash", "bruising",
    },
    "metformin": {
        "nausea", "vomiting", "diarrhoea", "abdominal pain", "lactic acidosis",
        "decreased appetite", "metallic taste",
    },
    "atorvastatin": {
        "myalgia", "muscle pain", "rhabdomyolysis", "elevated liver enzymes",
        "headache", "nausea", "diarrhoea",
    },
    "sertraline": {
        "nausea", "insomnia", "diarrhoea", "dry mouth", "dizziness",
        "fatigue", "sexual dysfunction", "hyperhidrosis", "tremor",
        "suicidal ideation", "agitation",
    },
    "warfarin": {
        "bleeding", "haemorrhage", "hemorrhage", "bruising", "nosebleed",
        "blood in urine", "blood in stool", "gum bleeding",
    },
    "amoxicillin": {
        "diarrhoea", "nausea", "rash", "urticaria", "anaphylaxis",
        "vomiting", "abdominal pain",
    },
    "gabapentin": {
        "somnolence", "dizziness", "ataxia", "fatigue", "nystagmus",
        "tremor", "diplopia", "respiratory depression",
    },
    "pregabalin": {
        "somnolence", "dizziness", "ataxia", "fatigue", "weight gain",
        "peripheral oedema", "dry mouth",
    },
    "levothyroxine": {
        "palpitations", "tachycardia", "tremor", "headache", "insomnia",
        "weight loss", "sweating", "diarrhoea", "heat intolerance",
    },
    "rivaroxaban": {
        "bleeding", "haemorrhage", "hemorrhage", "nausea", "anaemia",
        "elevated liver enzymes", "pruritus",
    },
    "semaglutide": {
        "nausea", "vomiting", "diarrhoea", "constipation", "abdominal pain",
        "pancreatitis", "decreased appetite", "injection site reaction",
    },
    # --- expanded demo corpus drugs (offline label surrogate) ---
    "ciprofloxacin": {
        "nausea", "diarrhoea", "vomiting", "rash", "tendinitis", "tendon rupture",
        "hepatic injury", "liver injury", "hepatotoxicity", "dizziness",
        "peripheral neuropathy", "qt prolongation", "photosensitivity",
    },
    "levofloxacin": {
        "nausea", "diarrhoea", "tendinitis", "tendon rupture", "hepatic injury",
        "hepatotoxicity", "dizziness", "peripheral neuropathy", "qt prolongation",
    },
    "prednisone": {
        "hyperglycaemia", "hypertension", "osteoporosis", "mood change",
        "insomnia", "weight gain", "infection", "cushingoid", "oedema",
    },
    "naproxen": {
        "nausea", "dyspepsia", "abdominal pain", "diarrhoea", "dizziness",
        "headache", "rash", "gastrointestinal bleeding", "gi bleeding",
        "gastric ulcer", "hypertension", "oedema",
    },
    "diphenhydramine": {
        "somnolence", "drowsiness", "dizziness", "dry mouth", "urinary retention",
        "confusion", "blurred vision",
    },
    "fentanyl": {
        "respiratory depression", "somnolence", "nausea", "vomiting", "constipation",
        "pruritus", "dizziness", "dependence",
    },
    "codeine": {
        "nausea", "vomiting", "constipation", "somnolence", "dizziness",
        "respiratory depression", "itching",
    },
    "tramadol": {
        "nausea", "dizziness", "somnolence", "constipation", "vomiting",
        "seizure", "serotonin syndrome", "headache",
    },
    "morphine": {
        "nausea", "vomiting", "constipation", "somnolence", "respiratory depression",
        "pruritus", "dizziness", "urinary retention",
    },
    "paroxetine": {
        "nausea", "insomnia", "diarrhoea", "dry mouth", "dizziness", "fatigue",
        "sexual dysfunction", "suicidal ideation", "withdrawal",
    },
    "escitalopram": {
        "nausea", "insomnia", "diarrhoea", "dry mouth", "dizziness", "fatigue",
        "sexual dysfunction", "suicidal ideation", "qt prolongation",
    },
    "omeprazole": {
        "headache", "diarrhoea", "abdominal pain", "nausea", "flatulence",
        "vitamin b12 deficiency", "hypomagnesaemia", "fracture",
    },
    "lansoprazole": {
        "headache", "diarrhoea", "abdominal pain", "nausea", "constipation",
    },
    "ondansetron": {
        "headache", "constipation", "diarrhoea", "qt prolongation", "dizziness",
    },
    "methotrexate": {
        "nausea", "mucositis", "hepatotoxicity", "hepatic injury", "myelosuppression",
        "pneumonitis", "stomatitis", "fatigue",
    },
    "pioglitazone": {
        "oedema", "weight gain", "heart failure", "fracture", "bladder cancer",
        "hypoglycaemia",
    },
    "salbutamol": {
        "tremor", "palpitations", "tachycardia", "headache", "nervousness",
        "hypokalaemia",
    },
    "budesonide": {
        "oral candidiasis", "hoarseness", "cough", "headache", "nausea",
    },
    "paliperidone": {
        "somnolence", "extrapyramidal symptoms", "weight gain", "hyperprolactinaemia",
        "tachycardia", "orthostatic hypotension",
    },
    # vaccines — reactogenicity + known labeled events (offline surrogate)
    "covid-19 mrna vaccine": {
        "injection site pain", "fatigue", "headache", "myalgia", "chills", "fever",
        "nausea", "myocarditis", "pericarditis", "anaphylaxis", "lymphadenopathy",
    },
    "covid-19 vaccine": {
        "injection site pain", "fatigue", "headache", "myalgia", "chills", "fever",
        "nausea", "myocarditis", "pericarditis", "anaphylaxis",
    },
    "mmr vaccine": {
        "fever", "rash", "febrile convulsion", "febrile seizure", "lymphadenopathy",
        "parotitis", "thrombocytopenia", "anaphylaxis",
    },
    "hpv vaccine": {
        "injection site pain", "syncope", "headache", "fever", "nausea",
        "dizziness", "myalgia", "anaphylaxis",
    },
    "influenza vaccine": {
        "injection site pain", "fever", "myalgia", "malaise", "headache",
        "guillain-barre syndrome", "guillain-barré syndrome", "anaphylaxis",
    },
    "iron": {
        "constipation", "nausea", "abdominal pain", "diarrhoea", "dark stools",
        "vomiting",
    },
}


def _normalised(text: str) -> str:
    """Lowercase + collapse whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _event_in_text(event: str, pt: Optional[str], text_lower: str) -> bool:
    """Check if the event PT or its common synonyms appear in label text."""
    candidates = {_normalised(event)}
    if pt:
        candidates.add(_normalised(pt))
    # simple plural / singularisation
    for c in list(candidates):
        if c.endswith("s"):
            candidates.add(c[:-1])
        else:
            candidates.add(c + "s")
    return any(c in text_lower for c in candidates if len(c) > 2)


def _fetch_setid(drug_n: str, timeout: float = 3.0) -> Optional[str]:
    """Return DailyMed setid for a drug. Cached."""
    now = time.time()
    if drug_n in _SETID_CACHE and now - _SETID_CACHE[drug_n][0] < _TTL:
        return _SETID_CACHE[drug_n][1]
    try:
        url = f"{settings.dailymed_base_url}/spls.json"
        resp = httpx.get(url, params={"drug_name": drug_n, "pagesize": 1},
                         timeout=timeout)
        if resp.status_code == 200:
            rows = resp.json().get("data", []) or []
            setid = rows[0].get("setid") if rows else None
        else:
            setid = None
    except Exception:
        setid = None
    _SETID_CACHE[drug_n] = (now, setid)
    return setid


def _fetch_label_text(drug_n: str, timeout: float = 5.0) -> Optional[str]:
    """Return the concatenated adverse_reactions + warnings section text from DailyMed.

    Uses the /spls/{setid}/sections.json v2 endpoint.  Falls back gracefully if
    the network is unavailable.  Results are cached for _TTL seconds.
    """
    now = time.time()
    if drug_n in _SPL_CACHE and now - _SPL_CACHE[drug_n][0] < _TTL:
        return _SPL_CACHE[drug_n][1] or None

    label_text: Optional[str] = None
    try:
        setid = _fetch_setid(drug_n, timeout=timeout)
        if setid:
            url = f"{settings.dailymed_base_url}/spls/{setid}/sections.json"
            resp = httpx.get(url, timeout=timeout)
            if resp.status_code == 200:
                sections = resp.json().get("data", []) or []
                # Collect adverse_reactions + warnings sections (LOINC-code based titles)
                target_keywords = {
                    "adverse reaction", "adverse effect", "adverse event",
                    "undesirable effect", "side effect", "warning", "precaution",
                }
                parts = []
                for sec in sections:
                    title_l = (sec.get("title") or "").lower()
                    if any(kw in title_l for kw in target_keywords):
                        text = sec.get("text") or sec.get("section_text") or ""
                        if text:
                            parts.append(text)
                if parts:
                    label_text = " ".join(parts)
    except Exception:
        label_text = None

    _SPL_CACHE[drug_n] = (now, label_text or "")
    return label_text


def _classify_offline(drug_n: str, event: str, pt: Optional[str],
                      boxed_info: Optional[dict]) -> dict:
    """Offline classification using the curated synonym table."""
    # boxed tier: boxed_match already covers the event
    if boxed_info and boxed_info.get("covers_event"):
        return {
            "novelty_tier": "boxed",
            "label_match": True,
            "label_section": "boxed_warning",
            "confidence": "high",
            "note": "Already covered by an FDA boxed warning (offline surrogate registry).",
        }

    # Alias keys used in the demo corpus / vaccine naming
    aliases = {
        "covid vaccine": "covid-19 mrna vaccine",
        "covid-19 mrna": "covid-19 mrna vaccine",
        "mrna covid-19 vaccine": "covid-19 mrna vaccine",
        "pfizer vaccine": "covid-19 mrna vaccine",
        "moderna vaccine": "covid-19 mrna vaccine",
        "mmr": "mmr vaccine",
        "hpv": "hpv vaccine",
        "flu vaccine": "influenza vaccine",
        "influenza": "influenza vaccine",
        "acetaminophen": "paracetamol",
        "tylenol": "paracetamol",
        "advil": "ibuprofen",
        "motrin": "ibuprofen",
    }
    lookup_key = aliases.get(drug_n, drug_n)

    offline_rxns = _OFFLINE_REACTIONS.get(lookup_key, set())
    ev_l = _normalised(event)
    pt_l = _normalised(pt) if pt else ""
    match = (ev_l in offline_rxns or pt_l in offline_rxns
             or any(ev_l in r or r in ev_l for r in offline_rxns if len(r) > 3)
             or any(pt_l in r or r in pt_l for r in offline_rxns if pt_l and len(r) > 3))
    if match:
        return {
            "novelty_tier": "in_label",
            "label_match": True,
            "label_section": "adverse_reactions",
            "confidence": "medium",
            "note": ("Already listed in the adverse reactions section "
                     "(offline surrogate - verify against the full label)."),
        }

    if lookup_key in _OFFLINE_REACTIONS:
        # Drug is known, event not in our curated set -> novel
        return {
            "novelty_tier": "novel",
            "label_match": False,
            "label_section": None,
            "confidence": "medium",
            "note": ("This event does not appear in the current FDA label (offline surrogate) "
                     "- warrants priority review."),
        }

    # Drug known in boxed registry but not this event → treat as novel vs boxed harm
    if boxed_info and boxed_info.get("has_boxed") and not boxed_info.get("covers_event"):
        return {
            "novelty_tier": "novel",
            "label_match": False,
            "label_section": None,
            "confidence": "medium",
            "note": ("Drug carries a boxed warning for a different harm; this event is not "
                     "that boxed topic (offline surrogate)."),
        }

    # Drug itself is unknown in our offline table -> unknown
    return {
        "novelty_tier": "unknown",
        "label_match": None,
        "label_section": None,
        "confidence": "low",
        "note": ("No offline label surrogate for this product and DailyMed was unreachable. "
                 "Not a missing ingest source — labeling status could not be classified."),
    }


def assess_label_gap(
    drug: str,
    event: str,
    pt: Optional[str] = None,
    soc: Optional[str] = None,
    boxed_info: Optional[dict] = None,
    *,
    offline_only: bool = False,
) -> dict:
    """Classify a (drug → event) signal against the drug's current FDA label text.

    Parameters
    ----------
    drug:        raw drug name as detected in the signal.
    event:       raw symptom/event name.
    pt:          MedDRA Preferred Term (optional, improves matching).
    soc:         MedDRA System Organ Class (reserved for future use).
    boxed_info:  result of ``boxed_warnings.match()`` for this signal, if any.
    offline_only: skip DailyMed HTTP (used for bulk backfill).

    Returns
    -------
    dict with keys:
        novelty_tier  : "novel" | "in_label" | "boxed" | "unknown"
        label_match   : bool or None
        label_section : section name matched, or None
        confidence    : "high" | "medium" | "low"
        note          : plain-language explanation
    """
    drug_n = (normalize_drug(drug) or drug).strip().lower()

    # --- Tier 1: boxed warning covers the event -> "boxed" ---
    if boxed_info and boxed_info.get("covers_event"):
        return {
            "novelty_tier": "boxed",
            "label_match": True,
            "label_section": "boxed_warning",
            "confidence": "high",
            "note": ("Already covered by the FDA boxed (black-box) warning for this drug "
                     "- known-serious harm already prominently labelled."),
        }

    # --- Tier 2: try DailyMed live API (skipped on bulk offline refresh) ---
    label_text = None if offline_only else _fetch_label_text(drug_n)

    if label_text:
        text_lower = label_text.lower()
        if _event_in_text(event, pt, text_lower):
            # Identify which section (warning vs adverse_reactions)
            # by looking for the event near the keyword
            section = "adverse_reactions"
            warn_kws = ("warning", "precaution", "contraindication")
            ev_pos = text_lower.find(_normalised(event))
            if ev_pos > 0:
                context = text_lower[max(0, ev_pos - 200): ev_pos]
                if any(k in context for k in warn_kws):
                    section = "warnings_precautions"
            return {
                "novelty_tier": "in_label",
                "label_match": True,
                "label_section": section,
                "confidence": "high",
                "note": ("Already listed in the adverse reactions section of the current "
                         "FDA label (DailyMed live)."),
            }
        else:
            # Label text fetched but event not found -> novel
            return {
                "novelty_tier": "novel",
                "label_match": False,
                "label_section": None,
                "confidence": "high",
                "note": ("This event does not appear in the current FDA label "
                         "(DailyMed live search) - warrants priority review."),
            }

    # --- Tier 3: offline fallback ---
    return _classify_offline(drug_n, event, pt, boxed_info)


def refresh_label_novelty(db, project_id: int | None = None) -> dict:
    """Recompute label_novelty / label_gap_json for existing Signal rows (no full recompute)."""
    import json
    from sqlalchemy import or_

    from ..models import Signal
    from .boxed_warnings import match as boxed_match

    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(or_(Signal.project_id == project_id, Signal.project_id.is_(None), Signal.project_id == 0))

    counts = {"novel": 0, "in_label": 0, "boxed": 0, "unknown": 0, "not_applicable": 0, "updated": 0}
    for s in q.all():
        ptype = (s.product_type or "drug").lower()
        if ptype == "device":
            gap = {
                "novelty_tier": "not_applicable",
                "label_match": None,
                "label_section": None,
                "confidence": "high",
                "note": "Device signals are not classified against drug labels (use IMDRF/MAUDE context instead).",
            }
        else:
            boxed = boxed_match(s.drug or "", s.symptom or "", pt=s.meddra_pt, soc=s.meddra_soc)
            try:
                gap = assess_label_gap(
                    s.drug or "", s.symptom or "",
                    pt=s.meddra_pt, soc=s.meddra_soc, boxed_info=boxed,
                    offline_only=True,
                )
            except Exception:
                gap = {
                    "novelty_tier": "unknown",
                    "label_match": None,
                    "label_section": None,
                    "confidence": "low",
                    "note": "Label-gap assessment unavailable.",
                }
        tier = gap.get("novelty_tier") or "unknown"
        s.label_novelty = tier
        s.label_gap_json = json.dumps(gap)
        if tier in counts:
            counts[tier] += 1
        else:
            counts["unknown"] += 1
        counts["updated"] += 1
    db.commit()
    return counts
