"""Deterministic WHO-UMC causality assessment + severity grading.

Adapted from SignalRx/AyuScout. Fully offline: uses temporal / dechallenge /
rechallenge / confounder language cues. This runs alongside (not instead of) the
statistical disproportionality layer, giving each signal a clinical causality view.
"""
from __future__ import annotations

import re
from typing import List

_TEMPORAL = [
    "after taking", "after i took", "after starting", "started taking", "within hours",
    "within a day", "within days", "next day", "hours after", "days after", "soon after",
    "shortly after", "began after", "once i started",
]
_DECHALLENGE = ["stopped", "stopping", "discontinued", "quit taking", "went away after i stopped",
                "resolved after stopping", "stopped the drug"]
_RECHALLENGE = ["took again", "restarted", "started again", "came back when i took",
                "reappeared", "took it again"]
_CONFOUNDER = ["also taking", "also on", "other medication", "other drugs", "along with",
               "combined with", "as well as", "plus my"]

_CRITICAL_EVENTS = {
    "anaphylaxis", "anaphylactic reaction", "seizure", "convulsion",
    "liver damage", "hepatic injury", "hepatotoxicity",
    "kidney damage", "renal failure", "renal impairment",
    "bleeding", "haemorrhage", "hemorrhage",
    "suicidal thoughts", "suicidal ideation",
    "hallucinations", "hallucination",
    "difficulty breathing", "shortness of breath", "dyspnoea", "dyspnea",
    "chest pain", "irregular heartbeat", "arrhythmia",
    "jaundice", "fainting", "syncope",
    "swollen face", "face oedema", "allergic reaction", "hypersensitivity",
    "depression", "myocarditis", "guillain-barre syndrome",
}


# High-prior-risk products (Downing et al.: biologics, accelerated-approval,
# psychiatric therapeutics, and Class III devices are far likelier to accrue
# post-market safety events). Used as a weak Bayesian prior on causality.
_HIGH_RISK_DRUGS = {
    "isotretinoin", "clozapine", "quetiapine", "olanzapine", "risperidone",
    "sertraline", "fluoxetine", "venlafaxine", "valproate", "lamotrigine",
    "warfarin", "methotrexate", "montelukast", "varenicline", "natalizumab",
    "infliximab", "adalimumab", "rituximab", "semaglutide",
}
_BIOLOGIC_SUFFIXES = ("mab", "nib", "tinib", "cept", "kinra", "lizumab")


def _has_any(text: str, phrases: List[str]) -> bool:
    return any(p in text for p in phrases)


def _risk_prior(drug: str, product_type: str = "drug") -> float:
    d = (drug or "").lower()
    if product_type == "device":
        return 0.12  # device signals carry inherent malfunction-risk prior
    if d in _HIGH_RISK_DRUGS or any(d.endswith(sfx) for sfx in _BIOLOGIC_SUFFIXES):
        return 0.15
    return 0.0


def assess_causality(text: str, drug: str, symptom: str, fda_known: bool = False,
                     product_type: str = "drug") -> dict:
    t = (text or "").lower()
    factors = []
    score = 0.0

    temporal = _has_any(t, _TEMPORAL)
    if temporal:
        factors.append("temporal_relationship")
        score += 0.35
    dechallenge = _has_any(t, _DECHALLENGE)
    if dechallenge:
        factors.append("positive_dechallenge")
        score += 0.25
    rechallenge = _has_any(t, _RECHALLENGE)
    if rechallenge:
        factors.append("positive_rechallenge")
        score += 0.30
    confounder = _has_any(t, _CONFOUNDER)
    if confounder:
        factors.append("possible_confounder")
        score -= 0.20
    if fda_known:
        factors.append("known_reaction_openfda")
        score += 0.20

    prior = _risk_prior(drug, product_type)
    if prior > 0:
        factors.append("high_prior_risk_product")
        score += prior

    score = max(0.0, min(1.0, score))

    # Category. Social text rarely contains explicit de/rechallenge, which used to
    # collapse most signals to "Unassessable". We now let external evidence + a
    # temporal cue OR the risk prior reach at least "Possible", and carry an explicit
    # uncertainty level so the clinical reviewer sees how much to trust it.
    if temporal and dechallenge and rechallenge:
        category = "Certain"
    elif (temporal and dechallenge and not confounder) or (fda_known and dechallenge):
        category = "Probable"
    elif temporal or fda_known or prior > 0:
        category = "Possible"
    elif confounder:
        category = "Unlikely"
    else:
        category = "Unassessable"

    n_pos = len([f for f in factors if f != "possible_confounder"])
    if n_pos >= 3:
        uncertainty = "low"
    elif n_pos == 2:
        uncertainty = "medium"
    else:
        uncertainty = "high"

    return {"category": category, "score": round(score, 3), "factors": factors,
            "uncertainty": uncertainty}


def grade_severity(symptom: str, causality_category: str) -> str:
    sym = (symptom or "").lower()
    critical = sym in _CRITICAL_EVENTS
    if critical and causality_category in {"Certain", "Probable"}:
        return "Critical"
    if critical:
        return "High"
    if causality_category in {"Certain", "Probable"}:
        return "Medium"
    return "Low"
