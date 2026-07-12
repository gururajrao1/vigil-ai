"""Open MedDRA-style term standardization (surrogate).

MedDRA itself is licensed and cannot be bundled. This module provides an OPEN
drop-in surrogate: a curated mapping from common patient-reported symptom text to
a MedDRA-style Preferred Term (PT) and System Organ Class (SOC), following MedDRA's
27 SOC structure. Optionally enriches with a WHO ICD-11 code when ICD-11 API
credentials are configured (kept fully optional so the app runs offline/no-key).

This gives every signal a standardized, regulator-recognizable term + organ class
without redistributing licensed MedDRA content.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger("vigilai.meddra")

# System Organ Class labels (MedDRA-style)
SOC = {
    "NERV": "Nervous system disorders",
    "GI": "Gastrointestinal disorders",
    "SKIN": "Skin and subcutaneous tissue disorders",
    "PSYCH": "Psychiatric disorders",
    "CARD": "Cardiac disorders",
    "VASC": "Vascular disorders",
    "RESP": "Respiratory, thoracic and mediastinal disorders",
    "MUSC": "Musculoskeletal and connective tissue disorders",
    "HEPB": "Hepatobiliary disorders",
    "RENAL": "Renal and urinary disorders",
    "GEN": "General disorders and administration site conditions",
    "IMMUN": "Immune system disorders",
    "METAB": "Metabolism and nutrition disorders",
    "EYE": "Eye disorders",
    "EAR": "Ear and labyrinth disorders",
    "BLOOD": "Blood and lymphatic system disorders",
    "REPRO": "Reproductive system and breast disorders",
    "ENDO": "Endocrine disorders",
    "INFECT": "Infections and infestations",
}

# symptom surface (lowercase) -> (Preferred Term, SOC key)
_PT_MAP: Dict[str, tuple[str, str]] = {
    # Nervous system
    "headache": ("Headache", "NERV"),
    "migraine": ("Migraine", "NERV"),
    "dizziness": ("Dizziness", "NERV"),
    "vertigo": ("Vertigo", "EAR"),
    "drowsiness": ("Somnolence", "NERV"),
    "somnolence": ("Somnolence", "NERV"),
    "tremor": ("Tremor", "NERV"),
    "tremors": ("Tremor", "NERV"),
    "seizure": ("Seizure", "NERV"),
    "convulsions": ("Convulsion", "NERV"),
    "numbness": ("Hypoaesthesia", "NERV"),
    "tingling": ("Paraesthesia", "NERV"),
    "paresthesia": ("Paraesthesia", "NERV"),
    "paraesthesia": ("Paraesthesia", "NERV"),
    "confusion": ("Confusional state", "NERV"),
    "memory loss": ("Memory impairment", "NERV"),
    "brain fog": ("Cognitive disorder", "NERV"),
    "fainting": ("Syncope", "NERV"),
    "syncope": ("Syncope", "NERV"),
    # Psychiatric
    "anxiety": ("Anxiety", "PSYCH"),
    "panic attacks": ("Panic attack", "PSYCH"),
    "depression": ("Depression", "PSYCH"),
    "suicidal thoughts": ("Suicidal ideation", "PSYCH"),
    "suicidal ideation": ("Suicidal ideation", "PSYCH"),
    "mood swings": ("Mood swings", "PSYCH"),
    "irritability": ("Irritability", "PSYCH"),
    "agitation": ("Agitation", "PSYCH"),
    "hallucinations": ("Hallucination", "PSYCH"),
    "insomnia": ("Insomnia", "PSYCH"),
    "nightmares": ("Nightmare", "PSYCH"),
    "restlessness": ("Restlessness", "PSYCH"),
    "loss of libido": ("Libido decreased", "PSYCH"),
    "decreased libido": ("Libido decreased", "PSYCH"),
    # Gastrointestinal
    "nausea": ("Nausea", "GI"),
    "vomiting": ("Vomiting", "GI"),
    "diarrhea": ("Diarrhoea", "GI"),
    "diarrhoea": ("Diarrhoea", "GI"),
    "constipation": ("Constipation", "GI"),
    "abdominal pain": ("Abdominal pain", "GI"),
    "stomach pain": ("Abdominal pain", "GI"),
    "stomach ache": ("Abdominal pain", "GI"),
    "cramps": ("Abdominal pain", "GI"),
    "bloating": ("Abdominal distension", "GI"),
    "heartburn": ("Dyspepsia", "GI"),
    "acid reflux": ("Gastrooesophageal reflux disease", "GI"),
    "indigestion": ("Dyspepsia", "GI"),
    "loss of appetite": ("Decreased appetite", "METAB"),
    "increased appetite": ("Increased appetite", "METAB"),
    "mouth ulcers": ("Mouth ulceration", "GI"),
    "dry mouth": ("Dry mouth", "GI"),
    "difficulty swallowing": ("Dysphagia", "GI"),
    # Skin
    "rash": ("Rash", "SKIN"),
    "skin rash": ("Rash", "SKIN"),
    "itching": ("Pruritus", "SKIN"),
    "pruritus": ("Pruritus", "SKIN"),
    "hives": ("Urticaria", "SKIN"),
    "urticaria": ("Urticaria", "SKIN"),
    "hair loss": ("Alopecia", "SKIN"),
    "alopecia": ("Alopecia", "SKIN"),
    "dry skin": ("Dry skin", "SKIN"),
    "peeling skin": ("Skin exfoliation", "SKIN"),
    "photosensitivity": ("Photosensitivity reaction", "SKIN"),
    "sensitivity to light": ("Photophobia", "EYE"),
    "sweating": ("Hyperhidrosis", "SKIN"),
    "night sweats": ("Night sweats", "SKIN"),
    "flushing": ("Flushing", "VASC"),
    "hot flashes": ("Hot flush", "VASC"),
    "bruising": ("Contusion", "SKIN"),
    # Cardiac / vascular
    "palpitations": ("Palpitations", "CARD"),
    "chest pain": ("Chest pain", "CARD"),
    "irregular heartbeat": ("Arrhythmia", "CARD"),
    "arrhythmia": ("Arrhythmia", "CARD"),
    "tachycardia": ("Tachycardia", "CARD"),
    "bradycardia": ("Bradycardia", "CARD"),
    "low blood pressure": ("Hypotension", "VASC"),
    "hypotension": ("Hypotension", "VASC"),
    "high blood pressure": ("Hypertension", "VASC"),
    "hypertension": ("Hypertension", "VASC"),
    "swollen ankles": ("Peripheral swelling", "GEN"),
    "leg swelling": ("Peripheral swelling", "GEN"),
    "cold hands": ("Peripheral coldness", "VASC"),
    # Respiratory
    "shortness of breath": ("Dyspnoea", "RESP"),
    "breathlessness": ("Dyspnoea", "RESP"),
    "dyspnea": ("Dyspnoea", "RESP"),
    "difficulty breathing": ("Dyspnoea", "RESP"),
    "cough": ("Cough", "RESP"),
    "sore throat": ("Oropharyngeal pain", "RESP"),
    "wheezing": ("Wheezing", "RESP"),
    # Musculoskeletal
    "muscle pain": ("Myalgia", "MUSC"),
    "myalgia": ("Myalgia", "MUSC"),
    "muscle weakness": ("Muscular weakness", "MUSC"),
    "muscle cramps": ("Muscle spasms", "MUSC"),
    "joint pain": ("Arthralgia", "MUSC"),
    "arthralgia": ("Arthralgia", "MUSC"),
    "back pain": ("Back pain", "MUSC"),
    # Hepatobiliary / renal
    "liver damage": ("Hepatic injury", "HEPB"),
    "hepatotoxicity": ("Hepatotoxicity", "HEPB"),
    "jaundice": ("Jaundice", "HEPB"),
    "kidney damage": ("Renal impairment", "RENAL"),
    "renal failure": ("Renal failure", "RENAL"),
    "dark urine": ("Chromaturia", "RENAL"),
    "frequent urination": ("Pollakiuria", "RENAL"),
    "difficulty urinating": ("Dysuria", "RENAL"),
    "blood in urine": ("Haematuria", "RENAL"),
    # Blood / immune
    "bleeding": ("Haemorrhage", "BLOOD"),
    "nosebleed": ("Epistaxis", "BLOOD"),
    "blood in stool": ("Haematochezia", "GI"),
    "gum bleeding": ("Gingival bleeding", "GI"),
    "allergic reaction": ("Hypersensitivity", "IMMUN"),
    "allergy": ("Hypersensitivity", "IMMUN"),
    "allergies": ("Hypersensitivity", "IMMUN"),
    "allergic": ("Hypersensitivity", "IMMUN"),
    "angioedema": ("Angioedema", "IMMUN"),
    "adverse drug reaction": ("Adverse drug reaction", "GEN"),
    "adverse drug reactions": ("Adverse drug reaction", "GEN"),
    "adverse reaction": ("Adverse drug reaction", "GEN"),
    "adverse reactions": ("Adverse drug reaction", "GEN"),
    "adverse side effect": ("Adverse drug reaction", "GEN"),
    "adverse side effects": ("Adverse drug reaction", "GEN"),
    "adverse effect": ("Adverse drug reaction", "GEN"),
    "adverse effects": ("Adverse drug reaction", "GEN"),
    "side effect": ("Adverse drug reaction", "GEN"),
    "side effects": ("Adverse drug reaction", "GEN"),
    "adr": ("Adverse drug reaction", "GEN"),
    "anaphylaxis": ("Anaphylactic reaction", "IMMUN"),
    "swollen face": ("Face oedema", "IMMUN"),
    "swollen lips": ("Lip swelling", "IMMUN"),
    # General
    "fatigue": ("Fatigue", "GEN"),
    "tiredness": ("Fatigue", "GEN"),
    "weakness": ("Asthenia", "GEN"),
    "fever": ("Pyrexia", "GEN"),
    "chills": ("Chills", "GEN"),
    "swelling": ("Oedema", "GEN"),
    "edema": ("Oedema", "GEN"),
    "oedema": ("Oedema", "GEN"),
    "weight gain": ("Weight increased", "INVEST" if False else "METAB"),
    "weight loss": ("Weight decreased", "METAB"),
    "increased thirst": ("Thirst", "METAB"),
    # Eye / ear
    "blurred vision": ("Vision blurred", "EYE"),
    "double vision": ("Diplopia", "EYE"),
    "dry eyes": ("Dry eye", "EYE"),
    "hearing loss": ("Hypoacusis", "EAR"),
    "tinnitus": ("Tinnitus", "EAR"),
    "ringing in ears": ("Tinnitus", "EAR"),
    # Reproductive
    "erectile dysfunction": ("Erectile dysfunction", "REPRO"),
    "gynecomastia": ("Gynaecomastia", "REPRO"),
    # Vaccine adverse events of special interest (AESI) — Preferred Terms
    "myocarditis": ("Myocarditis", "CARD"),
    "myopericarditis": ("Myopericarditis", "CARD"),
    "pericarditis": ("Pericarditis", "CARD"),
    "guillain-barre syndrome": ("Guillain-Barre syndrome", "NERV"),
    "guillain-barré syndrome": ("Guillain-Barre syndrome", "NERV"),
    "guillain barre syndrome": ("Guillain-Barre syndrome", "NERV"),
    "thrombosis with thrombocytopenia": ("Thrombosis with thrombocytopenia", "VASC"),
    "cerebral venous sinus thrombosis": ("Cerebral venous sinus thrombosis", "VASC"),
    "bell's palsy": ("Facial paralysis", "NERV"),
    "bells palsy": ("Facial paralysis", "NERV"),
    "facial paralysis": ("Facial paralysis", "NERV"),
    "febrile seizure": ("Febrile convulsion", "NERV"),
    "febrile convulsion": ("Febrile convulsion", "NERV"),
    "immune thrombocytopenia": ("Immune thrombocytopenia", "BLOOD"),
    "thrombocytopenia": ("Thrombocytopenia", "BLOOD"),
    "encephalitis": ("Encephalitis", "NERV"),
    "acute disseminated encephalomyelitis": ("Acute disseminated encephalomyelitis", "NERV"),
}


# Reverse index: Preferred Term (lowercase) → (display PT, SOC key)
_PT_BY_NAME: Dict[str, tuple[str, str]] = {}
for _surface, (_pt, _soc) in _PT_MAP.items():
    _PT_BY_NAME[_pt.lower()] = (_pt, _soc)
    _PT_BY_NAME[_surface] = (_pt, _soc)


def known_preferred_terms() -> set[str]:
    """Set of MedDRA-surrogate Preferred Term display strings."""
    return {pt for pt, _ in _PT_MAP.values()}


def map_term(symptom: str) -> dict:
    """Return {pt, soc_code, soc, matched} for a symptom surface form.

    Matches surface synonyms and already-canonical Preferred Term names.
    Unmatched returns matched=False (callers must not treat title-case as clinical).
    """
    key = (symptom or "").strip().lower()
    if not key:
        return {"pt": "Unspecified", "soc_code": "GEN", "soc": SOC["GEN"], "matched": False}
    if key in _PT_MAP:
        pt, soc_key = _PT_MAP[key]
        return {"pt": pt, "soc_code": soc_key, "soc": SOC[soc_key], "matched": True}
    if key in _PT_BY_NAME:
        pt, soc_key = _PT_BY_NAME[key]
        return {"pt": pt, "soc_code": soc_key, "soc": SOC[soc_key], "matched": True}
    return {
        "pt": key.title(),
        "soc_code": "GEN",
        "soc": SOC["GEN"],
        "matched": False,
    }


def icd11_code(term: str) -> Optional[str]:
    """Optional WHO ICD-11 enrichment. Requires ICD11_CLIENT_ID/SECRET env vars.

    Returns None when not configured or offline, so it never blocks the pipeline.
    """
    import os

    cid = os.getenv("ICD11_CLIENT_ID", "").strip()
    secret = os.getenv("ICD11_CLIENT_SECRET", "").strip()
    if not (cid and secret):
        return None
    try:  # pragma: no cover - optional, network + credentials dependent
        import httpx

        token = httpx.post(
            "https://icdaccessmanagement.who.int/connect/token",
            data={"client_id": cid, "client_secret": secret,
                  "scope": "icdapi_access", "grant_type": "client_credentials"},
            timeout=5.0,
        ).json().get("access_token")
        if not token:
            return None
        r = httpx.get(
            "https://id.who.int/icd/release/11/2024-01/mms/search",
            params={"q": term},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                     "Accept-Language": "en", "API-Version": "v2"},
            timeout=5.0,
        )
        entities = r.json().get("destinationEntities", [])
        if entities:
            return entities[0].get("theCode")
    except Exception:
        return None
    return None
