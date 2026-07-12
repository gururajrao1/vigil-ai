"""Standardised MedDRA Query (SMQ) grouping — open surrogate.

Real MedDRA/SMQs are licensed and cannot be bundled. This module provides an OPEN
drop-in surrogate: a curated set of clinically important syndrome groupings, each
with "narrow" (specific) and "broad" (sensitive) member Preferred Terms, plus the
logic to (a) tag an individual signal with its SMQ membership and (b) aggregate
signals into SYNDROME-LEVEL disproportionality.

Why this matters: a drug may look weak on any single Preferred Term yet be strongly
disproportionate at the syndrome level (e.g. several different hepatic PTs that each
have few reports but together form a clear drug-induced-liver-injury pattern). Real
pharmacovigilance teams review by SMQ for exactly this reason.

Deterministic + offline. Reuses the disproportionality math for the group-level pool.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from .disproportionality import (
    CORRECTION,
    _chi_square_yates,
    _ebgm,
    _gamma_prior,
    _ic,
    _is_sdr,
    _prr_ci,
    _ror_ci,
)

# Each SMQ: narrow (specific PTs), broad (sensitive PTs / keywords). All lowercase.
# PTs align with app/nlp/meddra.py so signals actually match.
SMQS: Dict[str, dict] = {
    "DILI": {
        "name": "Drug-related hepatic disorders (DILI)",
        "soc": "Hepatobiliary disorders",
        "note": "Hepatocellular / cholestatic liver injury attributable to a product.",
        "narrow": {"hepatic injury", "hepatotoxicity", "hepatic failure",
                   "drug-induced liver injury"},
        "broad": {"jaundice", "hepatic enzyme increased", "hyperbilirubinaemia",
                  "dark urine", "chromaturia"},
    },
    "SCAR": {
        "name": "Severe cutaneous adverse reactions (SCAR)",
        "soc": "Skin and subcutaneous tissue disorders",
        "note": "SJS/TEN/DRESS and related severe skin reactions.",
        "narrow": {"stevens-johnson syndrome", "toxic epidermal necrolysis",
                   "drug reaction with eosinophilia and systemic symptoms",
                   "skin exfoliation", "erythema multiforme"},
        "broad": {"rash", "urticaria", "pruritus", "photosensitivity reaction",
                  "skin rash"},
    },
    "ANAPHYLAXIS": {
        "name": "Anaphylactic reaction",
        "soc": "Immune system disorders",
        "note": "Acute IgE-mediated / systemic hypersensitivity.",
        "narrow": {"anaphylactic reaction", "anaphylactic shock"},
        "broad": {"hypersensitivity", "urticaria", "face oedema", "lip swelling",
                  "angioedema", "allergic reaction"},
    },
    "TORSADE_QT": {
        "name": "Torsade de pointes / QT prolongation",
        "soc": "Cardiac disorders",
        "note": "Ventricular repolarisation liability and its sequelae.",
        "narrow": {"torsade de pointes", "electrocardiogram qt prolonged",
                   "ventricular tachycardia", "ventricular fibrillation"},
        "broad": {"arrhythmia", "palpitations", "tachycardia", "syncope"},
    },
    "AKI": {
        "name": "Acute renal failure",
        "soc": "Renal and urinary disorders",
        "note": "Acute kidney injury and markers of renal impairment.",
        "narrow": {"renal failure", "acute kidney injury", "renal impairment"},
        "broad": {"haematuria", "oliguria", "blood creatinine increased"},
    },
    "RHABDO": {
        "name": "Rhabdomyolysis / myopathy",
        "soc": "Musculoskeletal and connective tissue disorders",
        "note": "Muscle toxicity spectrum (classic statin liability).",
        "narrow": {"rhabdomyolysis", "myopathy",
                   "blood creatine phosphokinase increased"},
        "broad": {"myalgia", "muscular weakness", "muscle spasms"},
    },
    "HAEMORRHAGE": {
        "name": "Haemorrhage",
        "soc": "Blood and lymphatic system disorders",
        "note": "Bleeding events (anticoagulant / antiplatelet liability).",
        "narrow": {"haemorrhage", "gastrointestinal haemorrhage",
                   "cerebral haemorrhage", "haematochezia"},
        "broad": {"epistaxis", "gingival bleeding", "contusion", "haematuria"},
    },
    "SUICIDE": {
        "name": "Suicide / self-injury",
        "soc": "Psychiatric disorders",
        "note": "Suicidal ideation, attempt and related behaviour.",
        "narrow": {"suicidal ideation", "suicide attempt", "completed suicide",
                   "self-injurious behaviour"},
        "broad": {"depression", "depressed mood"},
    },
    "SEROTONIN": {
        "name": "Serotonin syndrome",
        "soc": "Nervous system disorders",
        "note": "Serotonergic toxidrome (often drug-interaction driven).",
        "narrow": {"serotonin syndrome"},
        "broad": {"agitation", "tremor", "hyperhidrosis", "confusional state",
                  "myoclonus"},
    },
    "CYTOPENIA": {
        "name": "Haematopoietic cytopenias / agranulocytosis",
        "soc": "Blood and lymphatic system disorders",
        "note": "Myelosuppression (thiopurine / clozapine liability).",
        "narrow": {"agranulocytosis", "neutropenia", "pancytopenia",
                   "aplastic anaemia", "myelosuppression"},
        "broad": {"leukopenia", "thrombocytopenia", "anaemia"},
    },
    "GI_INJURY": {
        "name": "Gastrointestinal perforation, ulceration & bleeding",
        "soc": "Gastrointestinal disorders",
        "note": "Upper/lower GI mucosal injury (NSAID liability).",
        "narrow": {"gastrointestinal perforation", "gastric ulcer", "peptic ulcer",
                   "gastrointestinal haemorrhage", "haematochezia"},
        "broad": {"abdominal pain", "dyspepsia", "gastrooesophageal reflux disease"},
    },
    "CONVULSION": {
        "name": "Convulsions",
        "soc": "Nervous system disorders",
        "note": "Seizure spectrum.",
        "narrow": {"seizure", "convulsion", "status epilepticus"},
        "broad": {"tremor", "myoclonus"},
    },
    "CARDIAC_FAILURE": {
        "name": "Cardiac failure",
        "soc": "Cardiac disorders",
        "note": "Reduced cardiac output / congestion.",
        "narrow": {"cardiac failure", "cardiac failure congestive",
                   "left ventricular dysfunction"},
        "broad": {"dyspnoea", "peripheral swelling", "oedema", "fatigue"},
    },
}


def _norm(x: str | None) -> str:
    return (x or "").strip().lower()


def smqs_for_event(pt: str | None, soc: str | None = None,
                   surface: str | None = None) -> List[dict]:
    """Return the SMQ memberships for an event.

    Matches the Preferred Term (preferred) or the raw surface form against each SMQ's
    narrow then broad member sets. Returns a list of {smq, name, scope, soc}.
    """
    terms = {_norm(pt), _norm(surface)}
    terms.discard("")
    out: List[dict] = []
    for key, smq in SMQS.items():
        scope = None
        if terms & smq["narrow"]:
            scope = "narrow"
        elif terms & smq["broad"]:
            scope = "broad"
        if scope:
            out.append({"smq": key, "name": smq["name"], "scope": scope,
                        "soc": smq["soc"]})
    return out


def event_in_smq(smq_key: str, pt: str | None, surface: str | None = None) -> str | None:
    """Return 'narrow'|'broad'|None for whether an event belongs to a given SMQ."""
    smq = SMQS.get(smq_key)
    if not smq:
        return None
    terms = {_norm(pt), _norm(surface)}
    terms.discard("")
    if terms & smq["narrow"]:
        return "narrow"
    if terms & smq["broad"]:
        return "broad"
    return None


def aggregate_smq(signals: List[dict]) -> List[dict]:
    """Syndrome-level disproportionality across member Preferred Terms.

    ``signals`` = list of signal dicts (drug, event PT, post_count). For each SMQ we
    pool member-PT reports per drug and compute group-level PRR/ROR/chi2/EBGM/IC + an
    SDR flag using the same regulator-style thresholds as the per-PT engine.
    """
    if not signals:
        return []

    total = sum(int(s.get("post_count") or 0) for s in signals)
    if total <= 0:
        return []

    drug_total: Dict[str, int] = defaultdict(int)
    for s in signals:
        drug_total[s["drug"]] += int(s.get("post_count") or 0)

    # First pass: collect (a, expected) cells across every drug x SMQ to fit one
    # shared Gamma prior (stable EBGM shrinkage), plus the per-cell breakdown.
    cells: List[dict] = []
    counts: List[float] = []
    expecteds: List[float] = []
    for key, smq in SMQS.items():
        # reports (per drug) whose event belongs to this SMQ + PT breakdown
        drug_a: Dict[str, int] = defaultdict(int)
        drug_pts: Dict[str, Counter] = defaultdict(Counter)
        smq_total = 0
        scope_seen: Dict[str, str] = {}
        for s in signals:
            scope = event_in_smq(key, s.get("meddra_pt") or s.get("symptom"),
                                 s.get("symptom"))
            if not scope:
                continue
            n = int(s.get("post_count") or 0)
            drug_a[s["drug"]] += n
            drug_pts[s["drug"]][s.get("meddra_pt") or s.get("symptom")] += n
            smq_total += n
            # a signal's SMQ is "narrow" if any member PT is narrow
            if scope == "narrow" or key not in scope_seen:
                scope_seen[key] = scope
        if smq_total == 0:
            continue
        for drug, a in drug_a.items():
            dt = drug_total[drug]
            expected = (dt * smq_total) / total if total else 0.0
            cells.append({
                "smq": key, "name": smq["name"], "soc": smq["soc"],
                "note": smq["note"], "drug": drug, "a": a,
                "drug_total": dt, "smq_total": smq_total,
                "expected": expected, "pts": dict(drug_pts[drug]),
            })
            counts.append(float(a))
            expecteds.append(expected)

    if not cells:
        return []

    alpha, beta = _gamma_prior(counts, expecteds)

    # Second pass: metrics per cell, grouped by SMQ.
    grouped: Dict[str, dict] = {}
    for c in cells:
        a = c["a"]
        b = c["drug_total"] - a
        cc = c["smq_total"] - a
        d = total - a - b - cc
        aa, bb, ccc, dd = a + CORRECTION, b + CORRECTION, cc + CORRECTION, d + CORRECTION
        prr, prr_low, prr_high = _prr_ci(aa, bb, ccc, dd)
        ror, ror_low, ror_high = _ror_ci(aa, bb, ccc, dd)
        chi2 = _chi_square_yates(a, b, cc, d)
        ic, ic025 = _ic(a, c["expected"])
        ebgm, eb05 = _ebgm(a, c["expected"], alpha, beta)
        sdr = _is_sdr(ic025, eb05, prr_low, chi2, a)

        entry = {
            "drug": c["drug"], "count": a,
            "prr": prr, "prr_ci": [prr_low, prr_high],
            "ror": ror, "chi_square": chi2,
            "ic": ic, "ic025": ic025, "ebgm": ebgm, "eb05": eb05,
            "sdr_flag": sdr,
            "member_pts": sorted(c["pts"].items(), key=lambda kv: -kv[1]),
        }
        g = grouped.setdefault(c["smq"], {
            "smq": c["smq"], "name": c["name"], "soc": c["soc"], "note": c["note"],
            "total_reports": c["smq_total"], "drugs": [],
        })
        g["drugs"].append(entry)

    out = []
    for g in grouped.values():
        g["drugs"].sort(key=lambda e: (e["eb05"], e["ic025"], e["prr"], e["count"]),
                        reverse=True)
        g["sdr_count"] = sum(1 for e in g["drugs"] if e["sdr_flag"])
        g["top_eb05"] = g["drugs"][0]["eb05"] if g["drugs"] else 0.0
        out.append(g)
    out.sort(key=lambda g: (g["sdr_count"], g["top_eb05"], g["total_reports"]),
             reverse=True)
    return out


def reference() -> dict:
    """The SMQ definitions (for a reference view)."""
    return {
        "smqs": [
            {"key": k, "name": v["name"], "soc": v["soc"], "note": v["note"],
             "narrow": sorted(v["narrow"]), "broad": sorted(v["broad"])}
            for k, v in SMQS.items()
        ],
        "count": len(SMQS),
        "note": "Open MedDRA-style SMQ surrogate — not licensed MedDRA SMQ content.",
    }
