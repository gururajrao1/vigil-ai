"""Vaccine pharmacovigilance — vaccine safety surveillance overlay.

Vaccine PV is a distinct discipline from drug PV: the products are biologicals given
to healthy people (so the benefit/risk calculus and the vocabulary differ), safety
review is organised around a curated list of **Adverse Events of Special Interest
(AESI)**, individual cases are graded against **Brighton Collaboration** diagnostic
case-definition levels, and near-real-time risk is quantified with self-controlled
designs such as the **Self-Controlled Risk Interval (SCRI)**.

This module adds those vaccine-specific methods to VigilAI, entirely offline and with
no licensed content:

* **Vaccine registry** — a curated list of vaccines (COVID-19 mRNA, influenza, HPV,
  MMR, hepatitis B, Tdap, pneumococcal, zoster, rotavirus) with recognition synonyms
  and ``is_vaccine(product)``.
* **AESI list** — Brighton / CEPI / SPEAC-aligned adverse events of special interest
  (anaphylaxis, myocarditis, pericarditis, Guillain-Barré syndrome, thrombosis with
  thrombocytopenia syndrome, Bell's palsy, febrile seizure, syncope, immune
  thrombocytopenia, encephalitis/ADEM…), each mapped to MedDRA-style Preferred Terms.
  ``aesi_for(pt, symptom)`` returns the matched AESI (or ``None``).
* **Brighton level** — a Level 1/2/3 diagnostic-certainty **surrogate** for a matched
  AESI, from the specificity of the matched term and corroborating volume.
* **SCRI** — a self-controlled **relative incidence (RI)** over the available onset
  timestamps, split into a risk window vs a control window (continuity-corrected, with
  a rough log-based CI). Because social-listening data lacks true per-patient
  vaccination dates, this is clearly labelled a **social-listening SCRI surrogate**.

Deterministic, offline, no external API or key. Faithful to the published vaccine-PV
methodology adapted for social-listening fields (Brighton/SCRI-style).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..nlp.lexicons import normalize_drug

# --------------------------------------------------------------------------- #
# Vaccine registry — curated generics + recognition synonyms (brands/idioms).
#   generic  : canonical vaccine name (matches app/nlp/lexicons.py GENERIC_DRUGS)
#   name     : human-readable label
#   platform : technology / antigen family
#   synonyms : lower-cased brand names and colloquial forms
# --------------------------------------------------------------------------- #
VACCINE_REGISTRY: List[dict] = [
    {
        "generic": "covid-19 mrna vaccine",
        "name": "COVID-19 mRNA vaccine",
        "platform": "mRNA",
        "synonyms": {"comirnaty", "spikevax", "pfizer-biontech", "pfizer vaccine",
                     "moderna vaccine", "covid-19 vaccine", "covid vaccine",
                     "covid-19 mrna vaccine", "mrna covid vaccine"},
    },
    {
        "generic": "influenza vaccine",
        "name": "Influenza (flu) vaccine",
        "platform": "Inactivated / recombinant",
        "synonyms": {"fluarix", "fluzone", "flucelvax", "fluad", "flublok",
                     "flu vaccine", "flu shot", "influenza vaccine"},
    },
    {
        "generic": "hpv vaccine",
        "name": "Human papillomavirus (HPV) vaccine",
        "platform": "Recombinant VLP",
        "synonyms": {"gardasil", "gardasil 9", "gardasil-9", "cervarix",
                     "hpv vaccine", "human papillomavirus vaccine"},
    },
    {
        "generic": "mmr vaccine",
        "name": "Measles–mumps–rubella (MMR) vaccine",
        "platform": "Live attenuated",
        "synonyms": {"priorix", "m-m-r ii", "mmr", "mmr vaccine",
                     "measles mumps rubella vaccine"},
    },
    {
        "generic": "hepatitis b vaccine",
        "name": "Hepatitis B vaccine",
        "platform": "Recombinant subunit",
        "synonyms": {"engerix", "engerix-b", "recombivax", "recombivax hb",
                     "heplisav", "heplisav-b", "hepatitis b vaccine", "hep b vaccine"},
    },
    {
        "generic": "tdap vaccine",
        "name": "Tetanus–diphtheria–acellular pertussis (Tdap) vaccine",
        "platform": "Toxoid / acellular subunit",
        "synonyms": {"boostrix", "adacel", "tdap", "tdap vaccine", "dtap", "dtap vaccine"},
    },
    {
        "generic": "pneumococcal vaccine",
        "name": "Pneumococcal conjugate/polysaccharide vaccine",
        "platform": "Conjugate / polysaccharide",
        "synonyms": {"prevnar", "prevnar 13", "prevnar 20", "pneumovax", "pneumovax 23",
                     "vaxneuvance", "pneumococcal vaccine"},
    },
    {
        "generic": "zoster vaccine",
        "name": "Herpes zoster (shingles) vaccine",
        "platform": "Recombinant adjuvanted subunit",
        "synonyms": {"shingrix", "zostavax", "zoster vaccine", "shingles vaccine"},
    },
    {
        "generic": "rotavirus vaccine",
        "name": "Rotavirus vaccine",
        "platform": "Live oral",
        "synonyms": {"rotarix", "rotateq", "rotavirus vaccine"},
    },
]

# generic -> registry entry, plus a flat synonym lookup
_BY_GENERIC: Dict[str, dict] = {v["generic"]: v for v in VACCINE_REGISTRY}
_SYNONYMS: Dict[str, str] = {}
for _v in VACCINE_REGISTRY:
    for _s in _v["synonyms"]:
        _SYNONYMS[_s] = _v["generic"]


def _norm(x: str | None) -> str:
    return (x or "").strip().lower()


def is_vaccine(product: str | None) -> bool:
    """True when ``product`` (brand or generic, any casing) is a known vaccine."""
    raw = _norm(product)
    if not raw:
        return False
    if raw in _BY_GENERIC or raw in _SYNONYMS:
        return True
    generic = _norm(normalize_drug(raw))
    if generic in _BY_GENERIC or generic in _SYNONYMS:
        return True
    # Generic catch-all so any "... vaccine" product is treated as a vaccine.
    return "vaccine" in raw or "vaccination" in raw or "vaccine" in generic


def vaccine_entry(product: str | None) -> Optional[dict]:
    """Return the registry entry for a vaccine product, or None."""
    raw = _norm(product)
    if raw in _BY_GENERIC:
        return _BY_GENERIC[raw]
    if raw in _SYNONYMS:
        return _BY_GENERIC[_SYNONYMS[raw]]
    generic = _norm(normalize_drug(raw))
    if generic in _BY_GENERIC:
        return _BY_GENERIC[generic]
    if generic in _SYNONYMS:
        return _BY_GENERIC[_SYNONYMS[generic]]
    return None


# --------------------------------------------------------------------------- #
# Adverse Events of Special Interest (AESI) — Brighton / CEPI / SPEAC aligned.
#   key         : short id
#   name        : AESI label
#   soc         : MedDRA-style System Organ Class
#   narrow      : specific diagnostic Preferred Terms (high diagnostic certainty)
#   broad       : supportive / non-specific terms (lower certainty)
#   note        : why it is an AESI for vaccines
# All member terms are lower-cased and align with app/nlp/meddra.py so real signals
# actually match.
# --------------------------------------------------------------------------- #
AESI_TABLE: List[dict] = [
    {
        "key": "anaphylaxis",
        "name": "Anaphylaxis",
        "soc": "Immune system disorders",
        "narrow": {"anaphylactic reaction", "anaphylactic shock", "anaphylaxis"},
        "broad": {"hypersensitivity", "urticaria", "angioedema", "face oedema",
                  "lip swelling", "allergic reaction"},
        "note": "Acute IgE-mediated systemic hypersensitivity within minutes-hours of "
                "immunisation; the archetypal vaccine AESI.",
    },
    {
        "key": "myocarditis",
        "name": "Myocarditis",
        "soc": "Cardiac disorders",
        "narrow": {"myocarditis", "myopericarditis"},
        "broad": {"chest pain", "palpitations", "dyspnoea", "arrhythmia"},
        "note": "Inflammation of the myocardium; a recognised rare AESI of COVID-19 "
                "mRNA vaccines, especially in young males after dose 2.",
    },
    {
        "key": "pericarditis",
        "name": "Pericarditis",
        "soc": "Cardiac disorders",
        "narrow": {"pericarditis"},
        "broad": {"chest pain", "pericardial effusion"},
        "note": "Inflammation of the pericardium; co-monitored with myocarditis for "
                "mRNA COVID-19 vaccines.",
    },
    {
        "key": "gbs",
        "name": "Guillain-Barré syndrome (GBS)",
        "soc": "Nervous system disorders",
        "narrow": {"guillain-barre syndrome", "guillain-barré syndrome",
                   "miller fisher syndrome"},
        "broad": {"paraesthesia", "muscular weakness", "hypoaesthesia",
                  "facial paralysis"},
        "note": "Acute immune-mediated polyradiculoneuropathy; historically linked to "
                "influenza vaccination (1976 swine-flu) and monitored for adenoviral "
                "COVID-19 vaccines.",
    },
    {
        "key": "tts",
        "name": "Thrombosis with thrombocytopenia syndrome (TTS)",
        "soc": "Vascular disorders",
        "narrow": {"thrombosis with thrombocytopenia", "thrombosis with thrombocytopenia syndrome",
                   "cerebral venous sinus thrombosis"},
        "broad": {"thrombosis", "thrombocytopenia", "cerebral haemorrhage", "haemorrhage"},
        "note": "Rare thrombosis at unusual sites with low platelets; an AESI for "
                "adenoviral-vector COVID-19 vaccines.",
    },
    {
        "key": "bells_palsy",
        "name": "Bell's palsy (facial paralysis)",
        "soc": "Nervous system disorders",
        "narrow": {"bell's palsy", "bells palsy", "facial paralysis", "facial paresis"},
        "broad": {"facial nerve disorder"},
        "note": "Acute peripheral facial-nerve palsy; a monitored neurological AESI.",
    },
    {
        "key": "febrile_seizure",
        "name": "Febrile seizure",
        "soc": "Nervous system disorders",
        "narrow": {"febrile convulsion", "febrile seizure"},
        "broad": {"seizure", "convulsion", "pyrexia"},
        "note": "Fever-associated seizure in young children; monitored for MMR/MMRV and "
                "influenza vaccines.",
    },
    {
        "key": "syncope",
        "name": "Syncope (vasovagal)",
        "soc": "Nervous system disorders",
        "narrow": {"syncope", "loss of consciousness"},
        "broad": {"dizziness", "presyncope"},
        "note": "Fainting, typically an immunisation-anxiety reaction rather than a "
                "product effect; common in adolescents (e.g. after HPV vaccine).",
    },
    {
        "key": "itp",
        "name": "Immune thrombocytopenia (ITP)",
        "soc": "Blood and lymphatic system disorders",
        "narrow": {"immune thrombocytopenia", "idiopathic thrombocytopenic purpura",
                   "immune thrombocytopenic purpura"},
        "broad": {"thrombocytopenia", "contusion", "petechiae", "epistaxis"},
        "note": "Immune-mediated platelet destruction; historically monitored for "
                "MMR-containing vaccines.",
    },
    {
        "key": "encephalitis_adem",
        "name": "Encephalitis / ADEM",
        "soc": "Nervous system disorders",
        "narrow": {"encephalitis", "acute disseminated encephalomyelitis", "adem",
                   "encephalomyelitis"},
        "broad": {"confusional state", "seizure", "convulsion"},
        "note": "Acute CNS inflammation / demyelination; a serious neurological AESI.",
    },
]

_AESI_BY_KEY: Dict[str, dict] = {a["key"]: a for a in AESI_TABLE}


def aesi_for(pt: str | None, symptom: str | None = None) -> Optional[dict]:
    """Return the AESI matched by a Preferred Term / symptom surface, or None.

    Matches the (lower-cased) MedDRA PT or the raw surface form against each AESI's
    narrow (specific) then broad (supportive) member sets. Returns a dict with the
    AESI metadata plus the matched ``scope`` ('narrow' | 'broad').
    """
    terms = {_norm(pt), _norm(symptom)}
    terms.discard("")
    if not terms:
        return None
    for aesi in AESI_TABLE:
        if terms & aesi["narrow"]:
            return {**_public_aesi(aesi), "scope": "narrow"}
    for aesi in AESI_TABLE:
        if terms & aesi["broad"]:
            return {**_public_aesi(aesi), "scope": "broad"}
    return None


def _public_aesi(aesi: dict) -> dict:
    return {"key": aesi["key"], "name": aesi["name"], "soc": aesi["soc"],
            "note": aesi["note"]}


# --------------------------------------------------------------------------- #
# Brighton Collaboration case-definition level (surrogate).
# Real Brighton case definitions grade a single case's diagnostic CERTAINTY as
# Level 1 (highest, definitive criteria met) → Level 3 (lowest, only supportive
# evidence). Social text gives us no clinical work-up, so we approximate the level
# from (a) how specific the matched term is (narrow diagnostic PT vs broad
# supportive symptom) and (b) how much corroborating volume exists.
# --------------------------------------------------------------------------- #
def brighton_level(scope: str, n_reports: int) -> dict:
    """Deterministic Brighton-level surrogate for a matched AESI.

    ``scope`` is 'narrow' (a specific diagnostic term was reported) or 'broad'
    (only supportive/non-specific symptoms). ``n_reports`` is the number of
    supporting reports behind the signal.
    """
    if scope == "narrow":
        if n_reports >= 4:
            level = 1
            label = "Level 1 (highest diagnostic certainty)"
            rationale = ("A specific diagnostic term for the AESI was reported with "
                         "consistent corroboration across multiple reports.")
        else:
            level = 2
            label = "Level 2 (intermediate diagnostic certainty)"
            rationale = ("A specific diagnostic term for the AESI was reported but with "
                         "limited corroborating volume.")
    else:
        level = 3
        label = "Level 3 (lowest diagnostic certainty)"
        rationale = ("Only supportive / non-specific symptoms were reported — "
                     "insufficient to meet a specific case definition.")
    return {
        "level": level,
        "label": label,
        "scope": scope,
        "rationale": rationale,
        "note": "Social-listening surrogate for a Brighton Collaboration case-definition "
                "level; Brighton-style certainty from social text.",
    }


# --------------------------------------------------------------------------- #
# Self-Controlled Risk Interval (SCRI) — social-listening surrogate.
# The SCRI design compares the incidence of an event in a defined RISK window after
# vaccination against a CONTROL window in the same individuals (self-controlled, so
# fixed confounders cancel). Social data has no true per-patient vaccination date, so
# we approximate: anchor at the earliest supporting-post onset, treat a short window
# after the anchor as the risk interval and the remainder as the control interval, and
# take the (continuity-corrected) incidence ratio. Clearly a surrogate.
# --------------------------------------------------------------------------- #
_RISK_WINDOW_DAYS = 21.0     # canonical post-immunisation risk interval
_CC = 0.5                    # continuity correction


def scri(timestamps: List[datetime], risk_window_days: float = _RISK_WINDOW_DAYS) -> dict:
    """Compute a self-controlled relative incidence (RI) surrogate from onset times.

    Returns ``{ri, risk_n, control_n, risk_days, control_days, ci, method, note}``.
    ``ri`` is None when there is insufficient temporal spread to define both windows.
    """
    ts = sorted(t for t in (timestamps or []) if t is not None)
    base = {
        "ri": None,
        "risk_n": 0,
        "control_n": 0,
        "risk_days": None,
        "control_days": None,
        "ci": [None, None],
        "method": "self-controlled risk interval (SCRI) surrogate",
        "note": "Social-listening SCRI surrogate — anchored at the earliest reported "
                "onset (no true per-patient vaccination date is available).",
    }
    if len(ts) < 2:
        base["risk_n"] = len(ts)
        base["insufficient"] = True
        return base

    origin = ts[0]
    span_days = max((ts[-1] - origin).total_seconds() / 86400.0, 0.0)
    if span_days <= 0:
        base["risk_n"] = len(ts)
        base["insufficient"] = True
        return base

    # Ensure both windows exist: cap the risk window at half the observed span.
    risk_days = min(risk_window_days, span_days / 2.0)
    if risk_days <= 0:
        base["insufficient"] = True
        return base
    control_days = span_days - risk_days

    risk_n = 0
    control_n = 0
    for t in ts:
        delta = (t - origin).total_seconds() / 86400.0
        if delta < risk_days:
            risk_n += 1
        else:
            control_n += 1

    # Continuity-corrected incidence ratio + log-based 95% CI.
    rate_risk = (risk_n + _CC) / risk_days
    rate_control = (control_n + _CC) / control_days
    ri = rate_risk / rate_control
    log_se = math.sqrt(1.0 / (risk_n + _CC) + 1.0 / (control_n + _CC))
    lo = math.exp(math.log(ri) - 1.96 * log_se)
    hi = math.exp(math.log(ri) + 1.96 * log_se)

    return {
        "ri": round(ri, 2),
        "risk_n": risk_n,
        "control_n": control_n,
        "risk_days": round(risk_days, 1),
        "control_days": round(control_days, 1),
        "ci": [round(lo, 2), round(hi, 2)],
        "elevated": bool(lo > 1.0),
        "method": "self-controlled risk interval (SCRI) surrogate",
        "note": "Social-listening SCRI surrogate — anchored at the earliest reported "
                "onset (no true per-patient vaccination date is available).",
    }


# --------------------------------------------------------------------------- #
# Per-signal assessment + corpus aggregation.
# --------------------------------------------------------------------------- #
def assess(product: str, symptom: str, pt: str | None = None, soc: str | None = None,
           timestamps: Optional[List[datetime]] = None) -> dict:
    """Vaccine safety assessment for a (product -> event) signal.

    Returns ``{is_vaccine, vaccine_name, platform, aesi, brighton_level, scri}``.
    For non-vaccine products, ``is_vaccine`` is False and the overlay is empty.
    """
    if not is_vaccine(product):
        return {"is_vaccine": False, "aesi": None, "brighton_level": None, "scri": None}

    entry = vaccine_entry(product)
    aesi = aesi_for(pt, symptom)
    n_reports = len([t for t in (timestamps or []) if t is not None])
    brighton = brighton_level(aesi["scope"], n_reports) if aesi else None
    self_controlled = scri(timestamps or [])

    return {
        "is_vaccine": True,
        "vaccine_name": entry["name"] if entry else (product or "").title(),
        "platform": entry["platform"] if entry else None,
        "aesi": aesi,
        "aesi_name": aesi["name"] if aesi else None,
        "brighton_level": brighton,
        "scri": self_controlled,
    }


def summarize(assessment: dict | None) -> dict | None:
    """Compact vaccine summary to persist on an individual signal (vaccine_json)."""
    if not assessment or not assessment.get("is_vaccine"):
        return None
    aesi = assessment.get("aesi")
    brighton = assessment.get("brighton_level")
    scri_res = assessment.get("scri")
    return {
        "vaccine_name": assessment.get("vaccine_name"),
        "platform": assessment.get("platform"),
        "aesi_name": aesi["name"] if aesi else None,
        "aesi_key": aesi["key"] if aesi else None,
        "aesi_scope": aesi["scope"] if aesi else None,
        "aesi_soc": aesi["soc"] if aesi else None,
        "brighton_level": brighton["level"] if brighton else None,
        "brighton_label": brighton["label"] if brighton else None,
        "brighton_rationale": brighton["rationale"] if brighton else None,
        "scri": scri_res,
    }


def vaccine_aesi_summary(signals: List[dict]) -> dict:
    """Aggregate vaccine signals into an AESI-level summary for the reference endpoint.

    ``signals`` = signal dicts already serialized (must carry ``is_vaccine``, ``aesi``,
    ``drug``, ``vaccine`` overlay, ``post_count``). Groups by AESI and lists the
    contributing vaccine → event rows with Brighton level + SCRI relative incidence.
    """
    groups: Dict[str, dict] = {}
    total_vaccine_signals = 0
    for s in signals:
        if not s.get("is_vaccine"):
            continue
        total_vaccine_signals += 1
        vac = s.get("vaccine") or {}
        aesi_name = vac.get("aesi_name") or s.get("aesi")
        if not aesi_name:
            continue
        key = vac.get("aesi_key") or aesi_name
        g = groups.setdefault(key, {
            "aesi_key": key,
            "aesi_name": aesi_name,
            "soc": vac.get("aesi_soc"),
            "note": _AESI_BY_KEY.get(key, {}).get("note"),
            "signals": [],
            "total_reports": 0,
            "vaccines": set(),
        })
        scri_res = vac.get("scri") or {}
        g["signals"].append({
            "signal_id": s.get("id"),
            "vaccine": s.get("drug"),
            "vaccine_name": vac.get("vaccine_name"),
            "event": (s.get("meddra") or {}).get("pt") or s.get("symptom"),
            "brighton_level": vac.get("brighton_level"),
            "brighton_label": vac.get("brighton_label"),
            "scri_ri": scri_res.get("ri"),
            "scri_ci": scri_res.get("ci"),
            "risk_n": scri_res.get("risk_n"),
            "control_n": scri_res.get("control_n"),
            "post_count": s.get("post_count"),
            "sdr_flag": s.get("sdr_flag"),
        })
        g["total_reports"] += int(s.get("post_count") or 0)
        g["vaccines"].add(s.get("drug"))

    out = []
    for g in groups.values():
        g["n_vaccines"] = len(g["vaccines"])
        g["vaccines"] = sorted(v for v in g["vaccines"] if v)
        g["signals"].sort(key=lambda r: ((r["scri_ri"] or 0), r["post_count"] or 0),
                          reverse=True)
        # best (highest-certainty) Brighton level in the group
        levels = [r["brighton_level"] for r in g["signals"] if r["brighton_level"]]
        g["best_brighton_level"] = min(levels) if levels else None
        out.append(g)
    out.sort(key=lambda g: (g["total_reports"], g["n_vaccines"]), reverse=True)
    return {
        "groups": out,
        "vaccine_signal_count": total_vaccine_signals,
        "aesi_count": len(out),
    }


def reference() -> dict:
    """Vaccine registry + AESI definitions (for a reference view)."""
    return {
        "vaccines": [
            {"generic": v["generic"], "name": v["name"], "platform": v["platform"],
             "synonyms": sorted(v["synonyms"])}
            for v in VACCINE_REGISTRY
        ],
        "aesi": [
            {"key": a["key"], "name": a["name"], "soc": a["soc"], "note": a["note"],
             "narrow": sorted(a["narrow"]), "broad": sorted(a["broad"])}
            for a in AESI_TABLE
        ],
        "vaccine_count": len(VACCINE_REGISTRY),
        "aesi_count": len(AESI_TABLE),
        "note": "Curated vaccine registry + Brighton/CEPI/SPEAC-aligned AESI list "
                "(offline surrogate). Brighton levels and SCRI relative incidence are "
                "social-listening field estimates.",
    }
