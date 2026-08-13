"""Drug–drug interaction (DDI) co-mention disproportionality.

Mines product pairs co-reported on the same AE post (or FAERS polypharmacy-style
multi-drug bags) and scores interaction-style disproportionality with a
mechanistic plausibility gate (Kontsioti CPT 2024 / Hauben-style DDI mining).

Ω-style metric (Norén additive model surrogate):
  For triad (A, B, event E):
    n_ab_e  = posts with both A and B and E
    n_a_e, n_b_e, n_e, n_ab, N
  expected under independence of A and B given E approximated as:
    E = n_a_e * n_b_e / n_e
  Ω ≈ log2((n_ab_e + 0.5) / (E + 0.5))
  Interaction flagged when Ω > 0 and n_ab_e ≥ 2 (with shrinkage).

Offline / deterministic. Not a validated interaction screening submission.
"""
from __future__ import annotations

import math
from collections import Counter
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from .mechanism import assess as mechanism_assess

CORRECTION = 0.5
_Z = 1.96

# Curated high-confidence interaction patterns (offline surrogate)
_KNOWN_DDI_PATTERNS: List[dict] = [
    {
        "id": "serotonin_syndrome",
        "drugs_a": {"sertraline", "fluoxetine", "paroxetine", "citalopram",
                    "escitalopram", "venlafaxine", "duloxetine", "tramadol",
                    "linezolid", "methylene blue"},
        "drugs_b": {"sertraline", "fluoxetine", "paroxetine", "citalopram",
                    "escitalopram", "venlafaxine", "duloxetine", "tramadol",
                    "linezolid", "mirtazapine", "ondansetron"},
        "events": {"serotonin syndrome", "hyperthermia", "clonus", "agitation",
                   "tremor", "myoclonus"},
        "note": "Serotonergic combination — classic DDI toxidrome",
    },
    {
        "id": "qt_polypharmacy",
        "drugs_a": {"amiodarone", "sotalol", "haloperidol", "citalopram",
                    "escitalopram", "ondansetron", "azithromycin", "methadone"},
        "drugs_b": {"amiodarone", "sotalol", "haloperidol", "citalopram",
                    "escitalopram", "ondansetron", "azithromycin", "methadone",
                    "erythromycin", "moxifloxacin"},
        "events": {"qt prolongation", "torsade de pointes", "arrhythmia",
                   "syncope", "cardiac arrest"},
        "note": "Additive hERG / QT risk with dual QT-prolonging agents",
    },
    {
        "id": "bleeding_anticoag_nsaid",
        "drugs_a": {"warfarin", "rivaroxaban", "apixaban", "dabigatran",
                    "edoxaban", "heparin", "enoxaparin"},
        "drugs_b": {"ibuprofen", "naproxen", "diclofenac", "aspirin",
                    "celecoxib", "ketorolac"},
        "events": {"haemorrhage", "hemorrhage", "gastrointestinal bleeding",
                   "gi bleeding", "bruising", "epistaxis"},
        "note": "Anticoagulant + NSAID bleeding potentiation",
    },
    {
        "id": "statin_cyp_inhibitor",
        "drugs_a": {"simvastatin", "atorvastatin", "lovastatin"},
        "drugs_b": {"clarithromycin", "erythromycin", "itraconazole",
                    "ketoconazole", "ritonavir", "cyclosporine", "gemfibrozil"},
        "events": {"rhabdomyolysis", "myopathy", "myalgia", "muscle pain",
                   "ck elevation"},
        "note": "CYP3A4 / transporter inhibition raising statin exposure",
    },
]


def _omega(n_abe: float, expected: float) -> Tuple[float, float]:
    """Ω and approximate lower 95% bound (shrinkage surrogate)."""
    obs = n_abe + CORRECTION
    exp = expected + CORRECTION
    omega = math.log2(obs / exp) if exp > 0 else 0.0
    var = (1.0 / (math.log(2) ** 2)) * ((1.0 / obs) + (1.0 / exp))
    omega025 = omega - _Z * math.sqrt(var)
    return round(omega, 3), round(omega025, 3)


def _plausibility(drug_a: str, drug_b: str, event: str) -> dict:
    """Combine mechanism assess for either drug + known DDI pattern match."""
    m_a = mechanism_assess(drug_a, event) or {}
    m_b = mechanism_assess(drug_b, event) or {}
    mech_hit = bool(m_a.get("plausible") or m_b.get("plausible"))

    a_l, b_l, e_l = drug_a.lower(), drug_b.lower(), event.lower()
    pattern_hit = None
    for pat in _KNOWN_DDI_PATTERNS:
        in_a = (a_l in pat["drugs_a"] and b_l in pat["drugs_b"]) or (
            b_l in pat["drugs_a"] and a_l in pat["drugs_b"]
        )
        if not in_a:
            continue
        if any(e_l == ev or e_l in ev or ev in e_l for ev in pat["events"]):
            pattern_hit = {"id": pat["id"], "note": pat["note"]}
            break
        # Soft match: both drugs in pattern even if event not listed
        if pattern_hit is None:
            pattern_hit = {"id": pat["id"], "note": pat["note"] + " (event soft-match)"}

    plausible = mech_hit or bool(pattern_hit)
    return {
        "plausible": plausible,
        "mechanism_a": m_a if m_a.get("plausible") else None,
        "mechanism_b": m_b if m_b.get("plausible") else None,
        "known_pattern": pattern_hit,
        "gate": "pass" if plausible else "review",
        "note": (
            "Plausibility gate: mechanistic link for either drug OR curated "
            "DDI pattern. Failures are not discarded — marked for clinical review."
        ),
    }


def mine_ddi(
    posts: List[dict],
    *,
    min_count: int = 2,
    require_plausible: bool = False,
    focus_drug: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Mine co-mention DDI candidates from multi-drug AE posts."""
    N = len(posts)
    if N == 0:
        return {"pairs": [], "n_posts": 0, "n_multi_drug": 0, "disclaimer": _DISCLAIMER}

    multi = [p for p in posts if len(p.get("drugs") or []) >= 2]
    n_multi = len(multi)

    # Counts
    event_counts: Counter = Counter()
    drug_event: Counter = Counter()
    pair_event: Counter = Counter()
    pair_counts: Counter = Counter()

    for p in multi:
        drugs = sorted({d for d in p["drugs"]})
        events = list({e for e in p["events"]})
        for e in events:
            event_counts[e] += 1
            for d in drugs:
                drug_event[(d, e)] += 1
            for a, b in combinations(drugs, 2):
                pair = (a, b) if a < b else (b, a)
                pair_event[(pair[0], pair[1], e)] += 1
                pair_counts[pair] += 1

    focus_l = focus_drug.lower() if focus_drug else None
    rows: List[dict] = []

    for (a, b, e), n_abe in pair_event.items():
        if n_abe < min_count:
            continue
        if focus_l and focus_l not in (a.lower(), b.lower()):
            continue

        n_e = event_counts[e]
        n_ae = drug_event[(a, e)]
        n_be = drug_event[(b, e)]
        expected = (n_ae * n_be / n_e) if n_e else 0.0
        omega, omega025 = _omega(float(n_abe), expected)

        # Interaction ROR surrogate: odds of E given AB vs odds given A-not-B or B-not-A
        # Simplified: compare pair rate to max single-drug rate
        rate_ab = n_abe / max(pair_counts[(a, b)], 1)
        rate_a = n_ae / max(sum(1 for p in multi if a in p["drugs"]), 1)
        rate_b = n_be / max(sum(1 for p in multi if b in p["drugs"]), 1)
        interaction_ror = round(
            (rate_ab / max(max(rate_a, rate_b), 1e-9)), 3
        ) if max(rate_a, rate_b) > 0 else None

        plaus = _plausibility(a, b, e)
        if require_plausible and not plaus["plausible"]:
            continue

        sdr = omega025 > 0 and n_abe >= min_count
        rows.append({
            "drug_a": a,
            "drug_b": b,
            "event": e,
            "count": int(n_abe),
            "expected": round(expected, 3),
            "omega": omega,
            "omega025": omega025,
            "interaction_ror": interaction_ror,
            "sdr_flag": sdr,
            "plausibility": plaus,
            "strength": (
                "STRONG" if sdr and n_abe >= 3 and plaus["plausible"]
                else "MODERATE" if sdr or (n_abe >= 3 and omega > 0)
                else "WEAK"
            ),
        })

    rows.sort(
        key=lambda r: (r["omega025"], r["omega"], r["count"]),
        reverse=True,
    )
    return {
        "pairs": rows[:limit],
        "n_posts": N,
        "n_multi_drug": n_multi,
        "min_count": min_count,
        "method": "Ω co-mention + mechanism/pattern plausibility gate",
        "disclaimer": _DISCLAIMER,
    }


_DISCLAIMER = (
    "DDI mining on social/FAERS co-mentions is a hypothesis generator. "
    "Ω/interaction-ROR are corpus surrogates — not validated interaction screens. "
    ""
)
