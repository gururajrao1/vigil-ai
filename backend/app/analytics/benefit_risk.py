"""Quantitative benefit–risk assessment (BRAT / MCDA framing + NNT vs NNH).

A safety signal is only actionable *relative to the drug's therapeutic benefit*:
a common but mild event on a life-saving drug is very different from a rare-but-
serious event on a marginal-benefit drug. This overlay contextualises each drug
signal with a structured, quantitative benefit–risk view:

* **Benefit** — a curated, OFFLINE benefit knowledge base keyed by drug (with an
  ATC pharmacological-class fallback) giving the drug's typical primary indication
  and an illustrative **NNT** (number-needed-to-treat) with the benefit outcome it
  buys, drawn from well-known literature ranges. Vaccines are framed with an
  **NNV** (number-needed-to-vaccinate).
* **Risk** — an illustrative **NNH** (number-needed-to-harm) for *this* signal's
  event, derived transparently from a severity-anchored background absolute-risk
  estimate scaled by causality and the report burden (NNH = 1 / absolute-risk-
  increase). Spontaneous reports give reporting ratios, not incidence, so the NNH
  is a clearly-labelled surrogate.
* **BRAT / MCDA** — a small multi-criteria value assessment that weighs the
  benefit (by NNT and how serious the outcome it prevents/treats is) against the
  risk (by NNH and this signal's severity), producing a numeric benefit–risk
  score, an NNT:NNH ratio ("treat N to benefit one vs harm one"), and a verdict
  (Favourable / Uncertain / Unfavourable).

IMPORTANT — this is an **illustrative surrogate framing**, NOT a regulatory
benefit–risk assessment. We lack trial efficacy data, so the NNT/NNV figures are
illustrative literature ranges and the NNH is a report-derived proxy. It is a
decision-support prompt for a human reviewer, not a determination.

Deterministic, OFFLINE, no external API or key.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..nlp.lexicons import normalize_drug
from .class_effect import atc_class_key
from .vaccine import is_vaccine, vaccine_entry

_SOURCE = ("Illustrative benefit–risk surrogate (curated offline evidence base). "
           "NNT/NNV are illustrative literature ranges; NNH is a report-derived "
           "proxy — NOT a regulatory benefit–risk assessment.")

# --------------------------------------------------------------------------- #
# Curated benefit knowledge base.
#   drugs         : generic names this entry applies to (lowercase)
#   atc_classes   : WHO ATC level-4 keys (first 5 chars) for class-level fallback
#   indication    : the drug's typical primary indication
#   nnt           : illustrative number-needed-to-treat (literature range)
#   benefit_outcome : the beneficial outcome one treated patient in NNT achieves
#   horizon       : the time horizon the NNT refers to
#   benefit_value : how clinically valuable the benefit outcome is [0..1]
#                   (preventing death/MI ≈ 1.0; symptom relief ≈ 0.4) — the MCDA
#                   benefit-criticality weight
#   source        : short illustrative literature note
# --------------------------------------------------------------------------- #
BENEFIT_KB: List[dict] = [
    {
        "id": "statins",
        "drugs": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin",
                  "lovastatin", "fluvastatin", "pitavastatin"],
        "atc_classes": ["C10AA"],
        "indication": "Prevention of atherosclerotic cardiovascular disease",
        "nnt": 100,
        "benefit_outcome": "prevent one major cardiovascular event (MI/stroke)",
        "horizon": "over ~5 years (primary prevention)",
        "benefit_value": 0.95,
        "source": "Illustrative: statin primary-prevention NNT ~100+ (thennt.com / CTT).",
    },
    {
        "id": "ssri_snri",
        "drugs": ["sertraline", "paroxetine", "fluoxetine", "citalopram",
                  "escitalopram", "fluvoxamine", "venlafaxine", "duloxetine"],
        "atc_classes": ["N06AB", "N06AX"],
        "indication": "Major depressive disorder / anxiety disorders",
        "nnt": 7,
        "benefit_outcome": "achieve a clinical treatment response (≥50% symptom reduction)",
        "horizon": "over 6–8 weeks",
        "benefit_value": 0.7,
        "source": "Illustrative: SSRI response NNT ~7 vs placebo (Cipriani et al.).",
    },
    {
        "id": "anticoagulant_af",
        "drugs": ["warfarin", "rivaroxaban", "apixaban", "dabigatran", "edoxaban",
                  "acenocoumarol"],
        "atc_classes": ["B01AF", "B01AA", "B01AE"],
        "indication": "Stroke prevention in atrial fibrillation",
        "nnt": 25,
        "benefit_outcome": "prevent one ischaemic stroke",
        "horizon": "per year of anticoagulation",
        "benefit_value": 0.95,
        "source": "Illustrative: oral anticoagulation for AF NNT ~25/yr (Hart et al.).",
    },
    {
        "id": "metformin",
        "drugs": ["metformin"],
        "atc_classes": ["A10BA"],
        "indication": "Type 2 diabetes glycaemic control",
        "nnt": 14,
        "benefit_outcome": "prevent one diabetes-related clinical endpoint",
        "horizon": "over ~10 years (UKPDS-style)",
        "benefit_value": 0.85,
        "source": "Illustrative: metformin any-diabetes-endpoint NNT ~14 (UKPDS 34).",
    },
    {
        "id": "ppi",
        "drugs": ["omeprazole", "esomeprazole", "pantoprazole", "lansoprazole",
                  "rabeprazole", "dexlansoprazole"],
        "atc_classes": ["A02BC"],
        "indication": "Erosive oesophagitis / peptic ulcer / GERD",
        "nnt": 3,
        "benefit_outcome": "heal oesophagitis / achieve durable symptom relief",
        "horizon": "over 8 weeks",
        "benefit_value": 0.4,
        "source": "Illustrative: PPI healing/symptom-relief NNT ~2–4.",
    },
    {
        "id": "glp1",
        "drugs": ["semaglutide", "liraglutide", "dulaglutide", "exenatide",
                  "tirzepatide", "lixisenatide"],
        "atc_classes": ["A10BJ", "A10BX"],
        "indication": "Type 2 diabetes / chronic weight management",
        "nnt": 4,
        "benefit_outcome": "achieve ≥5% weight loss / individual glycaemic target",
        "horizon": "over ~1 year",
        "benefit_value": 0.6,
        "source": "Illustrative: GLP-1 ≥5% weight-loss NNT ~2–4 (STEP/SUSTAIN).",
    },
    {
        "id": "sglt2",
        "drugs": ["dapagliflozin", "empagliflozin", "canagliflozin", "ertugliflozin"],
        "atc_classes": ["A10BK"],
        "indication": "Type 2 diabetes / heart failure / CKD",
        "nnt": 20,
        "benefit_outcome": "prevent one heart-failure hospitalisation / CKD progression",
        "horizon": "over ~2 years",
        "benefit_value": 0.85,
        "source": "Illustrative: SGLT2 HF/renal composite NNT ~15–25 (DAPA-HF/EMPEROR).",
    },
    {
        "id": "isotretinoin",
        "drugs": ["isotretinoin"],
        "atc_classes": ["D10BA"],
        "indication": "Severe nodulocystic / treatment-resistant acne",
        "nnt": 2,
        "benefit_outcome": "achieve durable clearance of severe acne",
        "horizon": "over a single 5–6 month course",
        "benefit_value": 0.6,
        "source": "Illustrative: isotretinoin durable remission is near-universal (NNT ~1–2).",
    },
    {
        "id": "bisphosphonate",
        "drugs": ["alendronate", "risedronate", "ibandronate", "zoledronic acid",
                  "zoledronate"],
        "atc_classes": ["M05BA"],
        "indication": "Osteoporosis fracture prevention",
        "nnt": 20,
        "benefit_outcome": "prevent one vertebral fracture",
        "horizon": "over ~3 years",
        "benefit_value": 0.7,
        "source": "Illustrative: bisphosphonate vertebral-fracture NNT ~15–20 (FIT).",
    },
    {
        "id": "acei_arb",
        "drugs": ["lisinopril", "enalapril", "ramipril", "captopril", "perindopril",
                  "benazepril", "quinapril", "losartan", "valsartan", "candesartan",
                  "telmisartan", "irbesartan", "olmesartan"],
        "atc_classes": ["C09AA", "C09CA"],
        "indication": "Hypertension / heart failure / chronic kidney disease",
        "nnt": 30,
        "benefit_outcome": "prevent one major cardiovascular or renal event",
        "horizon": "over ~4 years",
        "benefit_value": 0.85,
        "source": "Illustrative: RAAS-blockade CV/renal NNT ~25–40 (HOPE/ONTARGET).",
    },
    {
        "id": "beta_blocker",
        "drugs": ["metoprolol", "atenolol", "bisoprolol", "carvedilol", "nebivolol",
                  "propranolol", "labetalol"],
        "atc_classes": ["C07AB", "C07AG", "C07AA"],
        "indication": "Heart failure / post-MI secondary prevention / hypertension",
        "nnt": 23,
        "benefit_outcome": "prevent one death (post-MI / heart failure)",
        "horizon": "over ~1–2 years",
        "benefit_value": 0.9,
        "source": "Illustrative: beta-blocker post-MI mortality NNT ~20–25 (CIBIS/MERIT-HF).",
    },
    {
        "id": "triptan",
        "drugs": ["sumatriptan", "rizatriptan", "zolmitriptan", "eletriptan",
                  "naratriptan", "almotriptan"],
        "atc_classes": ["N02CC"],
        "indication": "Acute migraine",
        "nnt": 3,
        "benefit_outcome": "achieve pain freedom at 2 hours",
        "horizon": "per treated attack",
        "benefit_value": 0.45,
        "source": "Illustrative: triptan 2-hour pain-freedom NNT ~3–5.",
    },
    {
        "id": "nsaid",
        "drugs": ["ibuprofen", "naproxen", "diclofenac", "meloxicam", "celecoxib",
                  "ketorolac", "indomethacin", "etoricoxib", "aceclofenac",
                  "ketoprofen", "loxoprofen"],
        "atc_classes": ["M01AE", "M01AB", "M01AH", "M01AC", "M01AG"],
        "indication": "Acute pain / inflammation / osteoarthritis",
        "nnt": 3,
        "benefit_outcome": "achieve ≥50% pain relief",
        "horizon": "per treatment episode",
        "benefit_value": 0.4,
        "source": "Illustrative: NSAID ≥50% acute-pain relief NNT ~2–3 (Oxford league).",
    },
    {
        "id": "opioid",
        "drugs": ["morphine", "oxycodone", "codeine", "tramadol", "fentanyl",
                  "hydrocodone", "hydromorphone", "oxymorphone", "tapentadol",
                  "buprenorphine"],
        "atc_classes": ["N02AA", "N02AB", "N02AE", "N02AX", "N02AJ"],
        "indication": "Moderate-to-severe acute or cancer pain",
        "nnt": 4,
        "benefit_outcome": "achieve meaningful analgesia (≥50% relief)",
        "horizon": "per treatment episode",
        "benefit_value": 0.5,
        "source": "Illustrative: opioid acute-pain analgesia NNT ~3–4.",
    },
    {
        "id": "methotrexate",
        "drugs": ["methotrexate"],
        "atc_classes": ["L01BA", "L04AX"],
        "indication": "Rheumatoid arthritis / severe psoriasis",
        "nnt": 3,
        "benefit_outcome": "achieve an ACR20 clinical response",
        "horizon": "over ~6 months",
        "benefit_value": 0.7,
        "source": "Illustrative: methotrexate RA ACR20 NNT ~3.",
    },
    {
        "id": "corticosteroid",
        "drugs": ["prednisone", "prednisolone", "dexamethasone", "methylprednisolone",
                  "hydrocortisone", "betamethasone", "budesonide"],
        "atc_classes": ["H02AB", "H02AA"],
        "indication": "Inflammatory / autoimmune / allergic flares",
        "nnt": 3,
        "benefit_outcome": "achieve symptomatic disease control of a flare",
        "horizon": "per flare",
        "benefit_value": 0.55,
        "source": "Illustrative: systemic corticosteroid flare-control NNT ~2–4.",
    },
    {
        "id": "anticonvulsant",
        "drugs": ["carbamazepine", "oxcarbazepine", "phenytoin", "lamotrigine",
                  "valproate", "levetiracetam", "topiramate"],
        "atc_classes": ["N03AF", "N03AX", "N03AG", "N03AB"],
        "indication": "Epilepsy seizure control / neuralgia",
        "nnt": 4,
        "benefit_outcome": "achieve ≥50% seizure reduction",
        "horizon": "sustained over months",
        "benefit_value": 0.75,
        "source": "Illustrative: antiepileptic ≥50% seizure-reduction NNT ~3–5.",
    },
    {
        "id": "atypical_antipsychotic",
        "drugs": ["risperidone", "olanzapine", "quetiapine", "aripiprazole",
                  "paliperidone", "clozapine", "ziprasidone", "lurasidone"],
        "atc_classes": ["N05AH", "N05AX", "N05AE"],
        "indication": "Schizophrenia / bipolar disorder / acute psychosis",
        "nnt": 6,
        "benefit_outcome": "achieve a clinical response / prevent one relapse",
        "horizon": "over months",
        "benefit_value": 0.7,
        "source": "Illustrative: antipsychotic relapse-prevention NNT ~3–7 (Leucht et al.).",
    },
    {
        "id": "fluoroquinolone",
        "drugs": ["ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin",
                  "norfloxacin", "gemifloxacin"],
        "atc_classes": ["J01MA"],
        "indication": "Serious / resistant bacterial infection",
        "nnt": 3,
        "benefit_outcome": "achieve microbiological + clinical cure",
        "horizon": "per treatment course",
        "benefit_value": 0.55,
        "source": "Illustrative: appropriate antibiotic cure NNT ~2–4.",
    },
]

# --------------------------------------------------------------------------- #
# Vaccine benefit knowledge base — framed as NNV (number-needed-to-vaccinate).
#   generic (matches vaccine.VACCINE_REGISTRY) -> {indication, nnv, benefit_outcome,
#   horizon, benefit_value, source}
# --------------------------------------------------------------------------- #
VACCINE_BENEFIT_KB: Dict[str, dict] = {
    "covid-19 mrna vaccine": {
        "indication": "Prevention of symptomatic COVID-19 / severe disease",
        "nnv": 100, "benefit_outcome": "prevent one symptomatic COVID-19 case",
        "horizon": "over a high-transmission period", "benefit_value": 0.75,
        "source": "Illustrative NNV — varies strongly with circulating variant / incidence.",
    },
    "influenza vaccine": {
        "indication": "Prevention of seasonal influenza",
        "nnv": 71, "benefit_outcome": "prevent one case of influenza illness",
        "horizon": "per influenza season", "benefit_value": 0.5,
        "source": "Illustrative: influenza-vaccine NNV ~40–70 (Cochrane, healthy adults).",
    },
    "hpv vaccine": {
        "indication": "Prevention of HPV-related high-grade cervical lesions",
        "nnv": 40, "benefit_outcome": "prevent one high-grade cervical lesion (CIN2+)",
        "horizon": "long-term", "benefit_value": 0.85,
        "source": "Illustrative NNV for CIN2+ prevention.",
    },
    "mmr vaccine": {
        "indication": "Prevention of measles, mumps and rubella",
        "nnv": 7, "benefit_outcome": "prevent one measles case in an outbreak setting",
        "horizon": "durable", "benefit_value": 0.9,
        "source": "Illustrative NNV; measles is highly transmissible so NNV is low.",
    },
    "hepatitis b vaccine": {
        "indication": "Prevention of hepatitis B infection",
        "nnv": 50, "benefit_outcome": "prevent one chronic HBV infection",
        "horizon": "long-term", "benefit_value": 0.8,
        "source": "Illustrative NNV for chronic-HBV prevention.",
    },
    "tdap vaccine": {
        "indication": "Prevention of tetanus, diphtheria and pertussis",
        "nnv": 20, "benefit_outcome": "prevent one pertussis case",
        "horizon": "per booster interval", "benefit_value": 0.7,
        "source": "Illustrative NNV for pertussis prevention.",
    },
    "pneumococcal vaccine": {
        "indication": "Prevention of invasive pneumococcal disease",
        "nnv": 60, "benefit_outcome": "prevent one episode of invasive pneumococcal disease",
        "horizon": "over several years", "benefit_value": 0.75,
        "source": "Illustrative NNV for IPD prevention in at-risk adults.",
    },
    "zoster vaccine": {
        "indication": "Prevention of herpes zoster (shingles)",
        "nnv": 33, "benefit_outcome": "prevent one shingles episode",
        "horizon": "over several years", "benefit_value": 0.6,
        "source": "Illustrative: recombinant zoster vaccine NNV ~30–35 (ZOE-50/70).",
    },
    "rotavirus vaccine": {
        "indication": "Prevention of severe rotavirus gastroenteritis",
        "nnv": 20, "benefit_outcome": "prevent one rotavirus-related hospitalisation",
        "horizon": "in the first years of life", "benefit_value": 0.7,
        "source": "Illustrative NNV for severe-rotavirus prevention.",
    },
}

# --------------------------------------------------------------------------- #
# MCDA weights.
# --------------------------------------------------------------------------- #
# Severity-anchored illustrative background absolute risk of the harm event being
# attributable to the drug (per exposed patient). Serious events are rarer.
_SEVERITY_BASE_ARI: Dict[str, float] = {
    "Critical": 0.0009,
    "High": 0.004,
    "Medium": 0.015,
    "Low": 0.06,
}
# How heavily each severity of harm counts against the benefit (MCDA harm weight).
_SEVERITY_WEIGHT: Dict[str, float] = {
    "Critical": 1.0,
    "High": 0.6,
    "Medium": 0.2,
    "Low": 0.08,
}
# Causality tilts the attributable risk (a probable signal is more likely a true harm).
_CAUSALITY_MULT: Dict[str, float] = {
    "Certain": 1.4,
    "Probable": 1.2,
    "Possible": 1.0,
    "Unlikely": 0.6,
    "Unassessable": 0.9,
}

# indexes
_DRUG_INDEX: Dict[str, dict] = {}
_CLASS_INDEX: Dict[str, dict] = {}
for _e in BENEFIT_KB:
    for _d in _e["drugs"]:
        _DRUG_INDEX.setdefault(_d, _e)
    for _c in _e.get("atc_classes", []):
        _CLASS_INDEX.setdefault(_c, _e)


def _lookup_benefit(drug: str, atc: Optional[str]) -> Optional[dict]:
    """Find the benefit KB entry for a drug, by generic then by ATC class."""
    generic = (normalize_drug(drug) or "").strip().lower()
    entry = _DRUG_INDEX.get(generic)
    if entry:
        return entry
    ck = atc_class_key(atc)
    if ck:
        return _CLASS_INDEX.get(ck)
    return None


def _estimate_nnh(severity: Optional[str], who_umc: Optional[str],
                  report_count: int) -> tuple[float, int]:
    """Illustrative NNH from a severity-anchored background risk, scaled by causality
    and report burden. Returns (absolute_risk_increase, nnh)."""
    base = _SEVERITY_BASE_ARI.get(severity or "Low", _SEVERITY_BASE_ARI["Low"])
    caus = _CAUSALITY_MULT.get(who_umc or "Unassessable", 0.9)
    # Report burden: more supporting reports of the event nudge the attributable
    # risk up (up to ~3x at ~60 reports). A transparent proxy, not incidence.
    burden = 1.0 + min(int(report_count or 0), 60) / 30.0
    ari = base * caus * burden
    ari = max(1e-4, min(0.5, ari))
    nnh = int(round(1.0 / ari))
    return ari, max(1, nnh)


def assess(drug: str, atc: Optional[str], event: Optional[str], pt: Optional[str],
           severity: Optional[str], who_umc: Optional[str],
           report_count: int = 0) -> Optional[dict]:
    """Structured quantitative benefit–risk assessment for a drug/vaccine signal.

    Combines a curated benefit (NNT / NNV) with an illustrative NNH for THIS
    signal's event into an MCDA benefit–risk score + verdict. Returns ``None`` when
    the drug is not in the benefit knowledge base (so we never fabricate a benefit).
    """
    harm_outcome = pt or (event or "").title() or "the reported event"

    # --- benefit side (vaccine NNV branch, then drug NNT) --------------------- #
    is_vac = is_vaccine(drug)
    if is_vac:
        entry = vaccine_entry(drug)
        vkey = entry["generic"] if entry else (normalize_drug(drug) or "").strip().lower()
        vb = VACCINE_BENEFIT_KB.get(vkey)
        if not vb:
            return None
        metric = "NNV"
        n_benefit = int(vb["nnv"])
        indication = vb["indication"]
        benefit_outcome = vb["benefit_outcome"]
        horizon = vb["horizon"]
        benefit_value = float(vb["benefit_value"])
        benefit_source = vb["source"]
        product_label = "Vaccinate"
    else:
        entry = _lookup_benefit(drug, atc)
        if not entry:
            return None
        metric = "NNT"
        n_benefit = int(entry["nnt"])
        indication = entry["indication"]
        benefit_outcome = entry["benefit_outcome"]
        horizon = entry["horizon"]
        benefit_value = float(entry["benefit_value"])
        benefit_source = entry["source"]
        product_label = "Treat"

    # --- risk side ------------------------------------------------------------ #
    ari, nnh = _estimate_nnh(severity, who_umc, report_count)
    sev_w = _SEVERITY_WEIGHT.get(severity or "Low", _SEVERITY_WEIGHT["Low"])

    # --- MCDA value model ----------------------------------------------------- #
    # Per-patient benefit utility (probability of benefit weighted by its value) vs
    # severity-weighted per-patient harm utility.
    benefit_utility = benefit_value / n_benefit if n_benefit else 0.0
    harm_utility = sev_w / nnh if nnh else 0.0
    ratio_adj = benefit_utility / harm_utility if harm_utility > 0 else float("inf")
    lhh = nnh / n_benefit if n_benefit else 0.0  # raw likelihood helped vs harmed
    # Net favourable outcomes per 100 patients (illustrative).
    br_score = round(100.0 * (benefit_utility - harm_utility), 2)

    # --- verdict -------------------------------------------------------------- #
    if harm_utility <= 0 or (ratio_adj >= 1.8 and br_score > 0):
        verdict = "Favourable"
    elif ratio_adj >= 0.8:
        verdict = "Uncertain"
    else:
        verdict = "Unfavourable"
    # Serious-signal safety override: a Critical, causally-probable signal should
    # never read "Favourable" unless the benefit overwhelmingly dominates — it
    # warrants a human benefit–risk review.
    override = False
    if severity == "Critical" and (who_umc in {"Certain", "Probable"}):
        if verdict == "Favourable" and ratio_adj < 4.0:
            verdict = "Uncertain"
            override = True

    ratio_value = round(lhh, 1)
    nnt_nnh_ratio = f"1 : {ratio_value}"  # per 1 harmed, ~ratio_value benefit

    rationale = _rationale(product_label, metric, n_benefit, benefit_outcome, nnh,
                           harm_outcome, severity, who_umc, ratio_value, verdict,
                           override)

    return {
        "metric": metric,                       # NNT | NNV
        "is_vaccine": is_vac,
        "indication": indication,
        "nnt": n_benefit,                        # NNT or NNV value
        "benefit_outcome": benefit_outcome,
        "benefit_horizon": horizon,
        "benefit_value": round(benefit_value, 2),
        "nnh": nnh,
        "harm_outcome": harm_outcome,
        "absolute_risk_increase": round(ari, 5),
        "severity_weight": sev_w,
        "nnt_nnh_ratio": nnt_nnh_ratio,
        "ratio_value": ratio_value,              # NNH / NNT (likelihood helped vs harmed)
        "br_score": br_score,                    # net favourable outcomes per 100 (illustrative)
        "verdict": verdict,                      # Favourable | Uncertain | Unfavourable
        "safety_override": override,
        "rationale": rationale,
        "illustrative": True,
        "source": f"{benefit_source} {_SOURCE}",
    }


def _rationale(product_label: str, metric: str, n_benefit: int, benefit_outcome: str,
               nnh: int, harm_outcome: str, severity: Optional[str],
               who_umc: Optional[str], ratio_value: float, verdict: str,
               override: bool) -> str:
    verb = "vaccinate" if metric == "NNV" else "treat"
    lead = (f"{product_label} ~{n_benefit} to {benefit_outcome} ({metric}={n_benefit}); "
            f"an illustrative ~1 in {nnh} exposed may experience "
            f"{harm_outcome.lower()} ({severity or 'Low'} severity, {who_umc or 'Unassessable'} "
            f"causality). ")
    ratio_txt = (f"That is roughly {ratio_value}× more people helped than harmed "
                 f"(NNT:NNH ≈ 1:{ratio_value}). ")
    if verdict == "Favourable":
        tail = ("On this illustrative surrogate the benefit clearly outweighs this "
                "signal's harm.")
    elif verdict == "Unfavourable":
        tail = ("On this illustrative surrogate the signal's harm rivals or exceeds "
                "the drug's benefit — prioritise review.")
    else:
        tail = ("On this illustrative surrogate the balance is uncertain — a human "
                "benefit–risk review is warranted.")
    if override:
        tail = ("This is a serious, causally-probable signal, so the balance is held "
                "at Uncertain pending clinical review regardless of the drug's benefit.")
    return lead + ratio_txt + tail


def summarize(assessment: Optional[dict]) -> Optional[dict]:
    """Identity pass-through kept for symmetry with the other overlays."""
    return assessment or None


# --------------------------------------------------------------------------- #
# Reference / aggregation views.
# --------------------------------------------------------------------------- #
def reference() -> dict:
    """Public reference view of the benefit knowledge base."""
    return {
        "count": len(BENEFIT_KB),
        "vaccine_count": len(VACCINE_BENEFIT_KB),
        "note": ("Curated offline benefit knowledge base (illustrative NNT/NNV literature "
                 "ranges) used to contextualise each signal against the drug's therapeutic "
                 "benefit. NNH is a report-derived surrogate. This is an illustrative "
                 "benefit–risk framing, NOT a regulatory benefit–risk assessment."),
        "severity_base_absolute_risk": _SEVERITY_BASE_ARI,
        "severity_weight": _SEVERITY_WEIGHT,
        "causality_multiplier": _CAUSALITY_MULT,
        "drugs": [
            {"indication": e["indication"], "drugs": e["drugs"],
             "atc_classes": e.get("atc_classes", []), "nnt": e["nnt"],
             "benefit_outcome": e["benefit_outcome"], "horizon": e["horizon"],
             "benefit_value": e["benefit_value"], "source": e["source"]}
            for e in BENEFIT_KB
        ],
        "vaccines": [
            {"vaccine": k, "indication": v["indication"], "nnv": v["nnv"],
             "benefit_outcome": v["benefit_outcome"], "horizon": v["horizon"],
             "benefit_value": v["benefit_value"], "source": v["source"]}
            for k, v in VACCINE_BENEFIT_KB.items()
        ],
    }


def verdict_distribution(rows: List[dict]) -> Dict[str, int]:
    """Count verdicts across a set of benefit–risk rows."""
    dist = {"Favourable": 0, "Uncertain": 0, "Unfavourable": 0}
    for r in rows:
        v = r.get("verdict")
        if v in dist:
            dist[v] += 1
    return dist


def drug_table(rows: List[dict]) -> List[dict]:
    """Collapse per-signal B–R rows to one row per (drug, indication), keeping the
    most concerning verdict — the drug-centric view for the Benefit–Risk page."""
    order = {"Unfavourable": 0, "Uncertain": 1, "Favourable": 2}
    by_drug: Dict[str, dict] = {}
    for r in rows:
        key = f"{(r.get('drug') or '').lower()}|{r.get('indication')}"
        cur = by_drug.get(key)
        if cur is None:
            by_drug[key] = {**r, "n_signals": 1,
                            "events": [r.get("harm_outcome")] if r.get("harm_outcome") else []}
            continue
        cur["n_signals"] += 1
        if r.get("harm_outcome") and r["harm_outcome"] not in cur["events"]:
            cur["events"].append(r["harm_outcome"])
        # keep the most concerning verdict + its NNH/ratio for the drug row
        if order.get(r.get("verdict"), 3) < order.get(cur.get("verdict"), 3):
            for f in ("verdict", "nnh", "harm_outcome", "nnt_nnh_ratio",
                      "ratio_value", "br_score", "severity", "who_umc",
                      "rationale", "safety_override", "signal_id"):
                if f in r:
                    cur[f] = r[f]
    out = list(by_drug.values())
    out.sort(key=lambda r: (order.get(r.get("verdict"), 3), r.get("ratio_value") or 0))
    return out


# --------------------------------------------------------------------------- #
# PrOACT-URL / BRAT quantitative balance (ClinicalTrials.gov optional)
# --------------------------------------------------------------------------- #
_PROACT_DISCLAIMER = (
    "Prototype PrOACT-URL / BRAT balance. Efficacy rates are ClinicalTrials.gov "
    "or curated offline surrogates; SAE rates are social/DMA-derived — NOT a "
    "CHMP/FDA benefit–risk determination."
)

# Offline efficacy response-rate cache (illustrative literature / label ranges)
_EFFICACY_CACHE: Dict[str, dict] = {
    "semaglutide": {"response_rate_pct": 62.0, "endpoint": "≥5% weight loss / HbA1c response", "source": "offline_label_surrogate"},
    "atorvastatin": {"response_rate_pct": 55.0, "endpoint": "LDL-C goal attainment", "source": "offline_literature_surrogate"},
    "sertraline": {"response_rate_pct": 50.0, "endpoint": "HAM-D response ≥50%", "source": "offline_literature_surrogate"},
    "warfarin": {"response_rate_pct": 70.0, "endpoint": "stroke prevention efficacy (relative)", "source": "offline_literature_surrogate"},
    "pembrolizumab": {"response_rate_pct": 40.0, "endpoint": "ORR (indication-dependent)", "source": "offline_literature_surrogate"},
    "tisagenlecleucel": {"response_rate_pct": 81.0, "endpoint": "ORR in relapsed/refractory ALL (illustrative)", "source": "offline_cber_surrogate"},
}


def _fetch_clinicaltrials_efficacy(drug: str, timeout: float = 3.0) -> Optional[dict]:
    """Best-effort ClinicalTrials.gov v2 query; returns None offline."""
    try:
        import json
        import urllib.request
        from urllib.parse import quote

        url = (
            "https://clinicaltrials.gov/api/v2/studies?"
            f"query.term={quote(drug)}&filter.phase=PHASE3&pageSize=5"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "VigilAI/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        studies = data.get("studies") or []
        if not studies:
            return None
        # Extract a crude primary outcome string; efficacy % rarely structured → mark unavailable
        proto = (studies[0].get("protocolSection") or {})
        outcomes = ((proto.get("outcomesModule") or {}).get("primaryOutcomes") or [])
        title = ""
        if outcomes:
            title = outcomes[0].get("measure") or outcomes[0].get("description") or ""
        return {
            "available": True,
            "source": "clinicaltrials_gov_v2",
            "n_studies": len(studies),
            "primary_endpoint": title or None,
            "response_rate_pct": None,  # structured % rarely present; fall back to cache
            "nct_sample": [
                (s.get("protocolSection") or {}).get("identificationModule", {}).get("nctId")
                for s in studies[:3]
            ],
        }
    except Exception:
        return None


def evaluate_benefit_risk_ratio(
    drug_id: str,
    primary_ae_pt: str,
    *,
    severe_ae_rate_pct: Optional[float] = None,
    post_count: int = 0,
    strength: str = "WEAK",
    offline_only: bool = False,
) -> dict:
    """PrOACT-URL style Balance Ratio = efficacy_response_% / severe_AE_signal_%."""
    drug_key = (normalize_drug(drug_id) or drug_id or "").lower().strip()
    efficacy = dict(_EFFICACY_CACHE.get(drug_key) or {})
    ct = None if offline_only else _fetch_clinicaltrials_efficacy(drug_id)
    if ct and ct.get("available"):
        if ct.get("response_rate_pct") is not None:
            efficacy["response_rate_pct"] = ct["response_rate_pct"]
            efficacy["source"] = ct["source"]
        efficacy["clinicaltrials"] = {
            "n_studies": ct.get("n_studies"),
            "primary_endpoint": ct.get("primary_endpoint"),
            "nct_sample": ct.get("nct_sample"),
        }
    if not efficacy.get("response_rate_pct"):
        # Fallback: map from BENEFIT_KB NNT → crude response surrogate 100/NNT capped
        benefit = None
        for e in BENEFIT_KB:
            if drug_key in e["drugs"]:
                benefit = e
                break
        if benefit and benefit.get("nnt"):
            efficacy = {
                "response_rate_pct": round(min(90.0, max(5.0, 100.0 / float(benefit["nnt"]) * 10)), 1),
                "endpoint": benefit.get("benefit_outcome"),
                "source": "derived_from_offline_nnt",
                "indication": benefit.get("indication"),
            }
        else:
            efficacy = {
                "response_rate_pct": 40.0,
                "endpoint": "unknown — default surrogate",
                "source": "default_offline",
            }

    # Severe AE signal rate surrogate from DMA strength + count
    if severe_ae_rate_pct is None:
        base = {"STRONG": 8.0, "MODERATE": 3.5, "WEAK": 1.2}.get((strength or "WEAK").upper(), 1.2)
        bump = min(10.0, (post_count or 0) * 0.15)
        severe_ae_rate_pct = round(base + bump, 2)
    severe_ae_rate_pct = max(0.01, float(severe_ae_rate_pct))
    bal = round(float(efficacy["response_rate_pct"]) / severe_ae_rate_pct, 3)

    if bal >= 5:
        tradeoff = "Benefit-dominant (efficacy >> severe AE signal rate)"
        tone = "favourable"
    elif bal >= 1.5:
        tradeoff = "Benefit leans ahead of severe AE burden — monitor"
        tone = "watch"
    elif bal >= 0.8:
        tradeoff = "Contested — efficacy and severe AE signal rates are close"
        tone = "uncertain"
    else:
        tradeoff = "Risk-dominant — severe AE signal rate rivals/exceeds efficacy"
        tone = "unfavourable"

    # Also attach classic BRAT assess when possible
    brat = None
    try:
        brat = assess(
            drug=drug_id,
            event=primary_ae_pt,
            severity="High" if (strength or "").upper() == "STRONG" else "Moderate",
            who_umc="Possible",
            post_count=post_count or 1,
            atc=None,
        )
    except Exception:
        brat = None

    return {
        "framework": "PrOACT-URL / BRAT",
        "drug": drug_id,
        "primary_ae_pt": primary_ae_pt,
        "efficacy": efficacy,
        "severe_ae_signal_rate_pct": severe_ae_rate_pct,
        "balance_ratio": bal,
        "balance_formula": "efficacy_response_rate_pct / severe_ae_signal_rate_pct",
        "tradeoff": tradeoff,
        "tone": tone,
        "brat": brat,
        "proact_dimensions": {
            "Problem": f"Benefit–risk for {drug_id} vs {primary_ae_pt}",
            "Objectives": "Maximise clinically meaningful benefit; minimise severe harm",
            "Alternatives": "Continue / RMMs / restrict / withdraw (human decision)",
            "Consequences": tradeoff,
            "Tradeoffs": f"Balance ratio = {bal}",
            "Uncertainty": "Social-listening SAE rate is a surrogate; trial efficacy may lag indication",
            "Risk_tolerance": "QPPV / safety board judgment required",
            "Linked_decisions": "Labeling, REMS/RMP, PBRER section 16–18",
        },
        "disclaimer": _PROACT_DISCLAIMER,
    }
