"""Class effect (ATC roll-up) + chemical read-across.

Two linked comparative-safety capabilities:

(A) **Class effect** — aggregate signals to the WHO **ATC pharmacological subgroup**
    (level-4, 5-char prefix, e.g. ``C10AA`` = HMG-CoA reductase inhibitors). For each
    (class, event) we pool member-drug reports and run the same disproportionality math
    at the class level, flagging a "class effect" when 2+ drugs in the class report the
    same event. A drug can look modest alone yet the class is clearly disproportionate.

(B) **Chemical read-across** — flag when a **structural analog** of the drug reports the
    same event ("analogs of this drug also report <event>"), an early class-wide warning
    even for a drug with sparse data. Uses a bundled curated analog/similarity table
    (Tanimoto-style scores per chemical family); no RDKit / heavy dependency required.

Deterministic + offline. Reuses the disproportionality engine for the group-level pool.
"""
from __future__ import annotations

from collections import defaultdict
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

# --------------------------------------------------------------------------- #
# ATC level-4 (pharmacological/chemical subgroup) human-readable names.
# Key = first 5 chars of the ATC code. Curated for common classes; unknown keys
# fall back to the raw prefix so the feature still works for any drug.
# --------------------------------------------------------------------------- #
ATC_CLASS_NAMES: Dict[str, str] = {
    "C10AA": "Statins (HMG-CoA reductase inhibitors)",
    "N06AB": "SSRIs (selective serotonin reuptake inhibitors)",
    "N06AX": "Other antidepressants",
    "M01AE": "Propionic-acid NSAIDs",
    "M01AB": "Acetic-acid NSAIDs",
    "M01AH": "Coxibs (COX-2 inhibitors)",
    "M01AC": "Oxicam NSAIDs",
    "B01AF": "Direct factor Xa inhibitors (DOACs)",
    "B01AA": "Vitamin-K antagonists",
    "B01AC": "Antiplatelet agents",
    "J01MA": "Fluoroquinolones",
    "J01CA": "Aminopenicillins",
    "J01CR": "Penicillin + beta-lactamase inhibitor",
    "J01FA": "Macrolides",
    "J01AA": "Tetracyclines",
    "C09AA": "ACE inhibitors",
    "C09CA": "Angiotensin-II receptor blockers (sartans)",
    "A02BC": "Proton-pump inhibitors",
    "A10BJ": "GLP-1 receptor agonists",
    "A10BK": "SGLT2 inhibitors",
    "A10BH": "DPP-4 inhibitors (gliptins)",
    "A10BG": "Thiazolidinediones",
    "N05BA": "Benzodiazepines (anxiolytic)",
    "N05CD": "Benzodiazepines (hypnotic)",
    "N02CC": "Triptans",
    "M05BA": "Bisphosphonates",
    "C07AB": "Beta blockers (selective)",
    "C07AG": "Alpha/beta blockers",
    "N03AF": "Carboxamide anticonvulsants",
    "N03AX": "Other anticonvulsants",
    "L01BC": "Antimetabolites (pyrimidine analogues)",
    "D10BA": "Systemic retinoids (acne)",
    "N02BE": "Anilides (paracetamol / acetaminophen)",
    "N02BA": "Salicylic-acid analgesics",
    "N06AA": "Tricyclic antidepressants",
    "N05AH": "Atypical antipsychotics (diazepines/oxazepines)",
    "A10BA": "Biguanides (metformin)",
}


# --------------------------------------------------------------------------- #
# Chemical read-across — curated structural-analog families with approximate
# Tanimoto-style similarity. Offline surrogate for a fingerprint search.
# --------------------------------------------------------------------------- #
_FAMILIES: List[Tuple[float, List[str]]] = [
    (0.82, ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin",
            "lovastatin", "fluvastatin", "pitavastatin"]),
    (0.78, ["sertraline", "paroxetine", "fluoxetine", "citalopram",
            "escitalopram", "fluvoxamine"]),
    (0.80, ["ibuprofen", "naproxen", "ketoprofen", "flurbiprofen", "loxoprofen",
            "dexketoprofen"]),
    (0.76, ["diclofenac", "aceclofenac", "indometacin", "ketorolac"]),
    (0.85, ["rivaroxaban", "apixaban", "edoxaban"]),
    (0.72, ["ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin",
            "norfloxacin"]),
    (0.80, ["lisinopril", "enalapril", "ramipril", "perindopril", "captopril"]),
    (0.82, ["losartan", "valsartan", "candesartan", "telmisartan", "irbesartan",
            "olmesartan"]),
    (0.84, ["omeprazole", "esomeprazole", "pantoprazole", "lansoprazole",
            "rabeprazole"]),
    (0.86, ["semaglutide", "liraglutide", "dulaglutide", "exenatide"]),
    (0.84, ["dapagliflozin", "empagliflozin", "canagliflozin"]),
    (0.80, ["sitagliptin", "saxagliptin", "linagliptin", "vildagliptin"]),
    (0.88, ["rosiglitazone", "pioglitazone"]),
    (0.75, ["amoxicillin", "ampicillin"]),
    (0.74, ["azithromycin", "clarithromycin", "erythromycin"]),
    (0.76, ["doxycycline", "minocycline", "tetracycline"]),
    (0.70, ["diazepam", "lorazepam", "alprazolam", "clonazepam", "temazepam"]),
    (0.82, ["sumatriptan", "rizatriptan", "zolmitriptan", "eletriptan"]),
    (0.80, ["alendronate", "risedronate", "ibandronate", "zoledronic acid"]),
    (0.78, ["metoprolol", "atenolol", "bisoprolol", "propranolol", "carvedilol",
            "nebivolol"]),
    (0.70, ["azathioprine", "mercaptopurine"]),
    (0.72, ["carbamazepine", "oxcarbazepine"]),
    (0.70, ["fluorouracil", "capecitabine"]),
]

# drug -> {analog: similarity}
_ANALOGS: Dict[str, Dict[str, float]] = defaultdict(dict)
for _sim, _members in _FAMILIES:
    for _a in _members:
        for _b in _members:
            if _a != _b:
                _ANALOGS[_a][_b] = _sim


def _norm(x: str | None) -> str:
    return (x or "").strip().lower()


def atc_class_key(atc: str | None) -> str | None:
    """WHO ATC level-4 (pharmacological subgroup) key = first 5 chars."""
    a = (atc or "").strip().upper()
    if len(a) >= 5:
        return a[:5]
    return a or None


def atc_class_name(key: str | None) -> str:
    if not key:
        return "Unclassified"
    return ATC_CLASS_NAMES.get(key, key)


def read_across(drug: str, event_pt: str,
                event_pairs: set[Tuple[str, str]]) -> List[dict]:
    """Structural analogs of ``drug`` that also report ``event_pt``.

    ``event_pairs`` = set of (drug_normalized, event_pt) present across all signals.
    Returns a list of {analog, similarity, analog_has_same_event} sorted by similarity.
    """
    d = _norm(drug)
    analogs = _ANALOGS.get(d, {})
    out: List[dict] = []
    for analog, sim in analogs.items():
        has = (analog, event_pt) in event_pairs
        out.append({"analog": analog, "similarity": round(sim, 2),
                    "analog_has_same_event": has})
    out.sort(key=lambda x: (x["analog_has_same_event"], x["similarity"]), reverse=True)
    return out


def aggregate_class(signals: List[dict]) -> List[dict]:
    """Class-level disproportionality per (ATC class, event).

    ``signals`` = list of {drug, atc, pt, soc, post_count} (drugs only). For each
    (class, event) we pool member-drug reports and compute group-level PRR/ROR/chi2/
    EBGM/IC + an SDR flag using the same regulator-style thresholds as the per-drug
    engine. ``class_effect`` is True when 2+ distinct drugs contribute.
    """
    rows = [s for s in signals if s.get("atc") and s.get("pt")]
    if not rows:
        return []

    total = sum(int(s.get("post_count") or 0) for s in rows)
    if total <= 0:
        return []

    class_total: Dict[str, int] = defaultdict(int)   # reports per ATC class
    event_total: Dict[str, int] = defaultdict(int)   # reports per event PT
    cell_a: Dict[Tuple[str, str], int] = defaultdict(int)          # (class, pt) -> a
    cell_drugs: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    class_soc: Dict[Tuple[str, str], str] = {}

    for s in rows:
        ck = atc_class_key(s["atc"])
        if not ck:
            continue
        pt = s["pt"]
        n = int(s.get("post_count") or 0)
        class_total[ck] += n
        event_total[pt] += n
        cell_a[(ck, pt)] += n
        cell_drugs[(ck, pt)][s["drug"]] += n
        class_soc.setdefault((ck, pt), s.get("soc"))

    # Fit one shared Gamma prior across all (class, event) cells for stable EBGM.
    keys = list(cell_a.keys())
    counts = [float(cell_a[k]) for k in keys]
    expecteds = [
        (class_total[ck] * event_total[pt]) / total if total else 0.0
        for (ck, pt) in keys
    ]
    alpha, beta = _gamma_prior(counts, expecteds)

    out: List[dict] = []
    for (ck, pt) in keys:
        a = cell_a[(ck, pt)]
        drugs = cell_drugs[(ck, pt)]
        expected = (class_total[ck] * event_total[pt]) / total if total else 0.0
        b = class_total[ck] - a
        c = event_total[pt] - a
        d = total - a - b - c
        aa, bb, cc, dd = a + CORRECTION, b + CORRECTION, c + CORRECTION, d + CORRECTION
        prr, prr_low, prr_high = _prr_ci(aa, bb, cc, dd)
        ror, ror_low, ror_high = _ror_ci(aa, bb, cc, dd)
        chi2 = _chi_square_yates(a, b, c, d)
        ic, ic025 = _ic(a, expected)
        ebgm, eb05 = _ebgm(a, expected, alpha, beta)
        sdr = _is_sdr(ic025, eb05, prr_low, chi2, a)
        member_list = sorted(drugs.items(), key=lambda kv: -kv[1])
        out.append({
            "class_key": ck,
            "class_name": atc_class_name(ck),
            "event": pt,
            "soc": class_soc.get((ck, pt)),
            "total_reports": a,
            "n_drugs": len(drugs),
            "class_effect": len(drugs) >= 2,
            "prr": prr, "prr_ci": [prr_low, prr_high],
            "ror": ror, "chi_square": chi2,
            "ic": ic, "ic025": ic025, "ebgm": ebgm, "eb05": eb05,
            "sdr_flag": sdr,
            "drugs": [{"drug": dr, "count": n} for dr, n in member_list],
        })

    out.sort(key=lambda g: (g["class_effect"], g["sdr_flag"], g["eb05"],
                            g["total_reports"]), reverse=True)
    return out


def build_lookup(groups: List[dict]) -> Dict[Tuple[str, str], dict]:
    """Index class-effect groups by (class_key, event) for per-signal attachment."""
    return {(g["class_key"], g["event"]): g for g in groups}


def class_summary(entry: dict | None) -> dict | None:
    """Compact class-level summary to persist on an individual signal."""
    if not entry:
        return None
    return {
        "class_key": entry["class_key"],
        "class_name": entry["class_name"],
        "event": entry["event"],
        "n_drugs": entry["n_drugs"],
        "class_effect": entry["class_effect"],
        "total_reports": entry["total_reports"],
        "prr": entry["prr"],
        "eb05": entry["eb05"],
        "ic025": entry["ic025"],
        "sdr_flag": entry["sdr_flag"],
        "member_drugs": [d["drug"] for d in entry["drugs"]],
    }


def active_comparator_analysis(
    class_inputs: List[dict],
) -> Dict[Tuple[str, str], dict]:
    """Active-comparator (same-class) disproportionality per (drug, event).

    Standard disproportionality contrasts a drug against **all other drugs**, which
    confounds by indication — drugs sharing an indication share the background event
    profile of the treated population. An **active comparator** restricts the contrast
    to the OTHER drugs in the same WHO ATC pharmacological subgroup, which share the
    indication, so a residual disproportion is more likely event/molecule-specific.

    For each (drug, event) with an ATC class we build a 2x2 restricted to the class
    cohort (reports involving class members only):

        a = this drug            + this event
        b = this drug            + other events   (in-class)
        c = same-class comparators + this event
        d = same-class comparators + other events

    and compute an active-comparator ROR and PRR with 95% CIs (reusing the frequentist
    log-SE helpers + Haldane-Anscombe +0.5 correction). ``stands_out_in_class`` is set
    when the AC ROR 95% CI lower bound still exceeds 1 (disproportionate even versus the
    drug's own class). A class with a single member drug has no active comparator and is
    handled gracefully with an explanatory note.

    ``class_inputs`` = list of {drug, atc, pt, soc, post_count} (drugs only). Returns a
    lookup keyed by (drug, event_pt) so each signal can be annotated in the pipeline.
    """
    rows = [s for s in class_inputs if s.get("atc") and s.get("pt")]
    if not rows:
        return {}

    class_drugs: Dict[str, set] = defaultdict(set)               # ck -> {drug}
    de_count: Dict[Tuple[str, str, str], int] = defaultdict(int)  # (ck, drug, pt) -> a
    drug_total: Dict[Tuple[str, str], int] = defaultdict(int)     # (ck, drug) -> reports
    event_total: Dict[Tuple[str, str], int] = defaultdict(int)    # (ck, pt) -> reports
    class_total: Dict[str, int] = defaultdict(int)                # ck -> reports

    for s in rows:
        ck = atc_class_key(s["atc"])
        if not ck:
            continue
        drug, pt, n = s["drug"], s["pt"], int(s.get("post_count") or 0)
        class_drugs[ck].add(drug)
        de_count[(ck, drug, pt)] += n
        drug_total[(ck, drug)] += n
        event_total[(ck, pt)] += n
        class_total[ck] += n

    out: Dict[Tuple[str, str], dict] = {}
    for (ck, drug, pt), a in de_count.items():
        class_name = atc_class_name(ck)
        comparators = sorted(class_drugs[ck] - {drug})
        n_comp = len(comparators)
        if n_comp == 0:
            out[(drug, pt)] = {
                "comparator_class": class_name,
                "class_key": ck,
                "event": pt,
                "n_comparator_drugs": 0,
                "comparator_drugs": [],
                "ac_ror": None,
                "ac_ror_ci": [None, None],
                "ac_prr": None,
                "ac_prr_ci": [None, None],
                "stands_out_in_class": False,
                "note": f"No active comparator available — {drug} is the only "
                        f"{class_name} member in the corpus, so a same-class "
                        f"contrast cannot be computed.",
            }
            continue

        b = drug_total[(ck, drug)] - a
        c = event_total[(ck, pt)] - a
        d = class_total[ck] - a - b - c
        aa, bb, cc, dd = a + CORRECTION, b + CORRECTION, c + CORRECTION, d + CORRECTION
        ror, ror_low, ror_high = _ror_ci(aa, bb, cc, dd)
        prr, prr_low, prr_high = _prr_ci(aa, bb, cc, dd)
        stands_out = ror_low > 1.0

        if stands_out:
            note = (f"Still disproportionate even compared to other {class_name} "
                    f"({n_comp} comparator drug{'s' if n_comp != 1 else ''}): the "
                    f"association is event/molecule-specific, not a shared "
                    f"class/indication effect.")
        elif ror < 1.0:
            note = (f"Attenuates within class — {drug} reports this event less than "
                    f"its {class_name} comparators, consistent with a class or "
                    f"indication effect rather than a molecule-specific risk.")
        else:
            note = (f"Attenuates within class — the disproportion weakens against "
                    f"same-class comparators (AC ROR CI includes 1), so the standard "
                    f"'vs all drugs' signal may partly reflect a shared "
                    f"class/indication effect.")

        out[(drug, pt)] = {
            "comparator_class": class_name,
            "class_key": ck,
            "event": pt,
            "n_comparator_drugs": n_comp,
            "comparator_drugs": comparators,
            "a": a, "b": b, "c": c, "d": d,
            "ac_ror": ror,
            "ac_ror_ci": [ror_low, ror_high],
            "ac_prr": prr,
            "ac_prr_ci": [prr_low, prr_high],
            "stands_out_in_class": stands_out,
            "note": note,
        }
    return out


def reference() -> dict:
    """Class + analog-family definitions (for a reference view)."""
    return {
        "atc_classes": [{"key": k, "name": v} for k, v in ATC_CLASS_NAMES.items()],
        "analog_families": [
            {"similarity": sim, "members": members} for sim, members in _FAMILIES
        ],
        "note": "ATC level-4 pharmacological subgroups + curated structural-analog "
                "families (offline Tanimoto surrogate; no RDKit dependency).",
    }
