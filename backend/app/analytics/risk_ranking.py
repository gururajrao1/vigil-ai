"""Subpopulation Risk Ranking & Stratification Engine.

Ranks patient cohorts by Risk Elevation Multiplier (REM) for a product–AE pair:

    REM = P(AE | Drug ∩ Subpopulation) / P(AE | Drug ∩ General Cohort)

Among drug-exposed reports, each demographic / comorbidity stratum is tested
with a Yates-corrected χ² against the complementary cohort. Segments are kept
when REM ≥ 1.5 and χ² ≥ 4.0 (unless exploratory mode), then ranked descending.

Feature attribution is a deterministic SHAP-style decomposition of the REM
excess across active stratum features (age, sex, comorbidity, region). Optional
sklearn / SHAP packages are used when present; otherwise the analytic share is
offline and reproducible.

Domain mitigation:
  • Pharmaceuticals → Section 5 Warnings / Contraindications language
  • Devices → Engineering redesign / procedure-protocol RCA triggers

Open MedDRA/UMLS/GMDN coding caches.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from .risk_strata import (
    _DISCLAIMER,
    _ONTOLOGY_STACK,
    _build_rows,
    _event_match,
    _product_match,
)

# Minimum statistical gates (clinical-lead defaults)
REM_MIN = 1.5
CHI2_MIN = 4.0
# Continuity correction (Haldane–Anscombe style on rates when sparse)
_EPS = 0.5


def _chi2_yates(a: float, b: float, c: float, d: float) -> float:
    """Yates-corrected χ² on a 2×2 table."""
    n = a + b + c + d
    if n <= 0:
        return 0.0
    num = n * (abs(a * d - b * c) - n / 2.0) ** 2
    den = (a + b) * (c + d) * (a + c) * (b + d)
    if den <= 0:
        return 0.0
    return float(num / den)


def _infer_domain(product: str, rows: List[dict]) -> str:
    p = (product or "").lower()
    if "vaccine" in p or "mrna" in p or p.startswith("mmr") or "immuniz" in p:
        return "vaccine"
    if any(tok in p for tok in (
        "catheter", "stent", "pump", "implant", "mesh", "defibrillator",
        "pacemaker", "endoscope", "cgm", "cpap",
    )):
        return "device"
    for r in rows[:40]:
        if _product_match(r.get("product", ""), product):
            pt = (r.get("product_type") or "drug").lower()
            if pt in ("vaccine", "device", "combination"):
                return pt
            return pt
    return "drug"


def _drug_exposed(rows: List[dict], product: str) -> List[dict]:
    out = []
    for r in rows:
        if (
            _product_match(r.get("product", ""), product)
            or any(_product_match(m, product) for m in (r.get("concomitant_meds") or []))
            or product in (r.get("text") or "").lower()
        ):
            out.append(r)
    return out


def _ae_flag(row: dict, ae: str) -> bool:
    return _event_match(row.get("events") or [], ae)


# --------------------------------------------------------------------------- #
# Stratum definitions — each returns membership predicate + feature labels
# --------------------------------------------------------------------------- #
def _stratum_defs() -> List[Dict[str, Any]]:
    def has_comorb(*labels: str):
        need = {x.lower() for x in labels}

        def pred(r: dict) -> bool:
            have = {c.lower() for c in (r.get("comorbidities") or [])}
            return bool(need & have)

        return pred

    return [
        {
            "id": "geriatric",
            "label": "Geriatric (age ≥ 65)",
            "features": ["age_bracket:GERIATRIC"],
            "pred": lambda r: r.get("age_bracket") == "GERIATRIC",
        },
        {
            "id": "pediatric",
            "label": "Pediatric (age < 18)",
            "features": ["age_bracket:PEDIATRIC"],
            "pred": lambda r: r.get("age_bracket") == "PEDIATRIC",
        },
        {
            "id": "female",
            "label": "Female",
            "features": ["sex:F"],
            "pred": lambda r: r.get("sex") == "F",
        },
        {
            "id": "male",
            "label": "Male",
            "features": ["sex:M"],
            "pred": lambda r: r.get("sex") == "M",
        },
        {
            "id": "renal",
            "label": "Pre-existing renal impairment",
            "features": ["comorbidity:renal_impairment"],
            "pred": has_comorb("renal failure", "chronic kidney disease"),
        },
        {
            "id": "chronic_wound",
            "label": "Chronic wound / DFU / necrosis",
            "features": ["comorbidity:chronic_wound"],
            "pred": has_comorb(
                "chronic wound", "diabetic foot ulcer", "diabetic foot",
                "pressure ulcer", "wound infection", "necrosis", "tissue necrosis",
                "skin erosion", "ulcer",
            ),
        },
        {
            "id": "diabetes",
            "label": "Diabetes mellitus",
            "features": ["comorbidity:diabetes"],
            "pred": has_comorb(
                "diabetes mellitus", "type 2 diabetes mellitus",
                "type 1 diabetes mellitus", "diabetic foot", "diabetic foot ulcer",
            ),
        },
        {
            "id": "cv",
            "label": "Cardiovascular comorbidity",
            "features": ["comorbidity:cardiovascular"],
            "pred": has_comorb("hypertension", "heart failure"),
        },
        {
            "id": "oncology",
            "label": "Oncology / malignancy history",
            "features": ["comorbidity:malignancy"],
            "pred": has_comorb("malignant neoplasm"),
        },
        {
            "id": "polypharmacy",
            "label": "Polypharmacy (≥2 concomitant products)",
            "features": ["polypharmacy"],
            "pred": lambda r: len(r.get("concomitant_meds") or []) >= 1,
        },
        {
            "id": "geriatric_renal",
            "label": "Geriatric ∩ renal impairment",
            "features": ["age_bracket:GERIATRIC", "comorbidity:renal_impairment"],
            "pred": lambda r: (
                r.get("age_bracket") == "GERIATRIC"
                and bool(
                    {c.lower() for c in (r.get("comorbidities") or [])}
                    & {"renal failure", "chronic kidney disease"}
                )
            ),
        },
        {
            "id": "geriatric_female",
            "label": "Geriatric ∩ female",
            "features": ["age_bracket:GERIATRIC", "sex:F"],
            "pred": lambda r: r.get("age_bracket") == "GERIATRIC" and r.get("sex") == "F",
        },
        {
            "id": "diabetes_wound",
            "label": "Diabetes ∩ chronic wound",
            "features": ["comorbidity:diabetes", "comorbidity:chronic_wound"],
            "pred": lambda r: (
                bool(
                    {c.lower() for c in (r.get("comorbidities") or [])}
                    & {
                        "diabetes mellitus", "type 2 diabetes mellitus",
                        "type 1 diabetes mellitus", "diabetic foot", "diabetic foot ulcer",
                    }
                )
                and bool(
                    {c.lower() for c in (r.get("comorbidities") or [])}
                    & {
                        "chronic wound", "diabetic foot ulcer", "diabetic foot",
                        "pressure ulcer", "necrosis", "ulcer", "skin erosion",
                    }
                )
            ),
        },
    ]


def _region_strata(exposed: List[dict]) -> List[Dict[str, Any]]:
    """Dynamic region strata when region is informative."""
    regions = sorted({
        (r.get("region") or "Global").strip()
        for r in exposed
        if (r.get("region") or "").strip() and (r.get("region") or "").lower() != "global"
    })
    out = []
    for reg in regions[:6]:
        out.append({
            "id": f"region_{reg.lower().replace(' ', '_')[:24]}",
            "label": f"Region · {reg}",
            "features": [f"region:{reg}"],
            "pred": (lambda region: (lambda r: (r.get("region") or "") == region))(reg),
        })
    return out


def _rate(pos: int, n: int) -> float:
    if n <= 0:
        return 0.0
    return (pos + _EPS) / (n + 2 * _EPS)


def _attribution_shares(
    features: List[str], rem: float, emp_single: Dict[str, float]
) -> List[dict]:
    """Decompose REM excess across active features (deterministic SHAP analogue).

    Each active feature's share of (REM − 1) is proportional to how much that
    feature alone elevates risk in the drug-exposed cohort. Shares sum to ~100%
    of the excess when REM > 1.
    """
    excess = max(rem - 1.0, 0.0)
    if excess <= 1e-9 or not features:
        return [{
            "factor": f,
            "shap_value": 0.0,
            "attribution_pct": round(100.0 / len(features), 1) if features else 0.0,
            "direction": "elevates",
            "note": "Flat REM — no excess to attribute",
        } for f in features]

    weights = []
    for f in features:
        # Single-feature REM contribution proxy (already computed where possible)
        w = max(emp_single.get(f, 1.0) - 1.0, 0.05)
        weights.append(w)
    s = sum(weights) or 1.0
    out = []
    for f, w in zip(features, weights):
        share = w / s
        out.append({
            "factor": f,
            "shap_value": round(excess * share, 4),
            "attribution_pct": round(100.0 * share, 1),
            "direction": "elevates",
            "note": (
                f"{f} accounts for ~{100.0 * share:.0f}% of the REM excess "
                f"(deterministic feature attribution)"
            ),
        })
    out.sort(key=lambda x: abs(x["shap_value"]), reverse=True)
    return out


def _try_optional_shap(
    X: List[List[float]], y: List[float], feature_names: List[str]
) -> Optional[Dict[str, float]]:
    """Optional TreeSHAP / linear SHAP when packages exist."""
    if len(X) < 20 or sum(y) < 3:
        return None
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        return None
    try:
        import shap  # type: ignore
    except ImportError:
        shap = None

    try:
        arr = np.asarray(X, dtype=float)
        yy = np.asarray(y, dtype=float)
        clf = LogisticRegression(max_iter=200, class_weight="balanced")
        clf.fit(arr, yy)
        if shap is not None:
            explainer = shap.LinearExplainer(clf, arr)
            sv = explainer.shap_values(arr)
            mean_abs = np.abs(sv).mean(axis=0)
            return {feature_names[i]: float(mean_abs[i]) for i in range(len(feature_names))}
        coef = clf.coef_.ravel()
        return {feature_names[i]: float(abs(coef[i])) for i in range(len(feature_names))}
    except Exception:
        return None


def mitigation_for(
    domain: str, product: str, ae: str, label: str, rem: float, top_factor: Optional[str]
) -> dict:
    """Rule-based risk-mitigation recommendations by product domain."""
    driver = top_factor or "subpopulation profile"
    if domain in ("device", "combination"):
        return {
            "domain": "device",
            "trigger": "engineering_or_procedure_rca",
            "headline": (
                f"High-risk procedure/demographic for {product} → {ae} "
                f"({label}, REM {rem:.2f}×)"
            ),
            "recommendations": [
                "Open a root-cause analysis for engineering redesign "
                "(material, geometry, sensor/firmware) aligned to IMDRF/GMDN coding.",
                "Review surgical / insertion / explant procedure protocol for this "
                f"subpopulation (driver: {driver}).",
                "Escalate to device vigilance board; cross-check MAUDE / MHRA FSNs "
                "for similar failure modes in this demographic.",
            ],
            "labeling_section": None,
            "gvp_hook": "Device vigilance — design / IFU / procedure mitigation",
        }
    if domain == "vaccine":
        return {
            "domain": "vaccine",
            "trigger": "aesi_cohort_monitoring",
            "headline": (
                f"AESI-style elevation for {product} → {ae} "
                f"({label}, REM {rem:.2f}×)"
            ),
            "recommendations": [
                "Flag AESI cohort monitoring with Brighton-style case definition review.",
                f"Prioritise follow-up ICSRs in this stratum (driver: {driver}).",
                "Consider targeted HCP communication for the elevated demographic.",
            ],
            "labeling_section": "Warnings and Precautions (vaccine product information)",
            "gvp_hook": "Vaccine AESI stratification",
        }
    # Pharmaceuticals (default)
    return {
        "domain": "pharmaceutical",
        "trigger": "labeling_section_5_or_contraindication",
        "headline": (
            f"Elevated subpopulation risk for {product} → {ae} "
            f"({label}, REM {rem:.2f}×)"
        ),
        "recommendations": [
            "Draft update for Section 5 (Warnings and Precautions) calling out "
            f"this subpopulation (driver: {driver}).",
            "Evaluate Contraindications / Dosage and Administration language if "
            f"REM ≥ 2 and χ² supports the stratum.",
            "Consider REMS-style risk mitigation or targeted HCP communication "
            "for the flagged demographic/comorbidity group.",
        ],
        "labeling_section": "Section 5 — Warnings and Precautions (and/or Contraindications)",
        "gvp_hook": "Signal validation → labeling / RMP consideration",
    }


def _score_stratum(
    exposed: List[dict],
    ae: str,
    stratum: Dict[str, Any],
    baseline_rate: float,
    single_feature_rem: Dict[str, float],
) -> Optional[dict]:
    pred: Callable[[dict], bool] = stratum["pred"]
    in_seg = [r for r in exposed if pred(r)]
    out_seg = [r for r in exposed if not pred(r)]
    n_in = len(in_seg)
    if n_in < 2:
        return None
    a = sum(1 for r in in_seg if _ae_flag(r, ae))
    b = n_in - a
    c = sum(1 for r in out_seg if _ae_flag(r, ae))
    d = len(out_seg) - c

    p_sub = _rate(a, n_in)
    p_gen = baseline_rate if baseline_rate > 0 else _rate(a + c, len(exposed))
    rem = (p_sub / p_gen) if p_gen > 1e-9 else (p_sub / 0.05)
    chi2 = _chi2_yates(float(a), float(b), float(c), float(d))

    features = list(stratum["features"])
    attrs = _attribution_shares(features, rem, single_feature_rem)
    top = attrs[0] if attrs else None
    narrative = None
    if top and rem >= REM_MIN:
        narrative = (
            f"{top['factor']} accounts for {top['attribution_pct']:.0f}% of the "
            f"risk spike (REM {rem:.2f}× vs general product-exposed cohort)."
        )

    return {
        "stratum_id": stratum["id"],
        "label": stratum["label"],
        "features": features,
        "n_subpopulation": n_in,
        "n_ae_in_subpopulation": int(a),
        "n_complement": len(out_seg),
        "n_ae_in_complement": int(c),
        "p_ae_subpopulation": round(p_sub, 4),
        "p_ae_general": round(p_gen, 4),
        "risk_elevation_multiplier": round(rem, 3),
        "relative_risk_elevation": round(rem, 3),  # UI alias
        "chi_square_yates": round(chi2, 3),
        "passes_gates": bool(rem >= REM_MIN and chi2 >= CHI2_MIN and a >= 2),
        "top_contributing_factors": attrs,
        "attribution_narrative": narrative,
        "table_2x2": {"a": a, "b": b, "c": c, "d": d},
    }


def rank_high_risk_populations(
    db: Session,
    product_id: str,
    target_ae_pt: str,
    *,
    top_n: int = 5,
    project_id: Optional[int] = None,
    include_exploratory: bool = False,
) -> dict:
    """Rank subpopulations by Risk Elevation Multiplier for a product–AE pair."""
    product = (product_id or "").strip().lower()
    ae = (target_ae_pt or "").strip().lower()
    top_n = max(1, min(int(top_n or 5), 25))

    if not product or not ae:
        return {
            "product_id": product_id or "",
            "target_ae_pt": target_ae_pt or "",
            "method": "risk_elevation_multiplier",
            "ranked": [],
            "needs_demo_seed": True,
            "verdict": "Provide both product_id and target_ae_pt.",
            "disclaimer": _DISCLAIMER,
            "formula": "REM = P(AE|Drug∩Subpop) / P(AE|Drug∩General)",
            "gates": {"rem_min": REM_MIN, "chi2_min": CHI2_MIN},
        }

    rows = _build_rows(db, project_id)
    exposed = _drug_exposed(rows, product)
    domain = _infer_domain(product, exposed or rows)

    n_exp = len(exposed)
    n_ae = sum(1 for r in exposed if _ae_flag(r, ae))
    baseline = _rate(n_ae, n_exp) if n_exp else 0.0

    if n_exp < 5 or n_ae < 2:
        return {
            "product_id": product,
            "target_ae_pt": ae,
            "product_domain": domain,
            "method": "risk_elevation_multiplier",
            "n_drug_exposed": n_exp,
            "n_ae_among_exposed": n_ae,
            "baseline_p_ae": round(baseline, 4),
            "ranked": [],
            "needs_demo_seed": True,
            "verdict": (
                f"Insufficient drug-exposed mass for {product} → {ae} "
                f"(n_exposed={n_exp}, n_ae={n_ae}). Load PV demo pack or Fetch sources."
            ),
            "how_to_use": (
                "Pass a product + AE with enough AE-flagged posts mentioning the product, "
                "then review ranked strata with REM ≥ 1.5 and χ² ≥ 4."
            ),
            "disclaimer": _DISCLAIMER,
            "ontology_stack": _ONTOLOGY_STACK,
            "formula": "REM = P(AE|Drug∩Subpop) / P(AE|Drug∩General)",
            "gates": {"rem_min": REM_MIN, "chi2_min": CHI2_MIN},
        }

    # Single-feature REM map for attribution weights
    single_feature_rem: Dict[str, float] = {}
    atomic = [s for s in _stratum_defs() if len(s["features"]) == 1]
    for s in atomic:
        scored = _score_stratum(exposed, ae, s, baseline, {})
        if scored:
            single_feature_rem[s["features"][0]] = scored["risk_elevation_multiplier"]

    # Optional global SHAP over one-hot of atomic features (enrichment only)
    feat_names = [s["features"][0] for s in atomic]
    X, y = [], []
    for r in exposed:
        X.append([1.0 if s["pred"](r) else 0.0 for s in atomic])
        y.append(1.0 if _ae_flag(r, ae) else 0.0)
    shap_map = _try_optional_shap(X, y, feat_names) or {}

    strata = _stratum_defs() + _region_strata(exposed)
    ranked: List[dict] = []
    for s in strata:
        scored = _score_stratum(exposed, ae, s, baseline, single_feature_rem)
        if not scored:
            continue
        if scored["risk_elevation_multiplier"] < REM_MIN:
            continue
        if not scored["passes_gates"]:
            if not include_exploratory:
                continue
            scored["exploratory"] = True
        else:
            scored["exploratory"] = False

        # Blend optional SHAP magnitudes into notes when available
        for fac in scored["top_contributing_factors"]:
            key = fac["factor"]
            if key in shap_map:
                fac["optional_shap_mean_abs"] = round(shap_map[key], 4)

        top_factor = (
            scored["top_contributing_factors"][0]["factor"]
            if scored["top_contributing_factors"] else None
        )
        mitigation = mitigation_for(
            domain, product, ae, scored["label"],
            scored["risk_elevation_multiplier"], top_factor,
        )
        seg_id = hashlib.sha1(
            f"{product}|{ae}|{scored['stratum_id']}".encode()
        ).hexdigest()[:10]
        ranked.append({
            **scored,
            "segment_id": seg_id,
            "product": product,
            "target_ae_pt": ae,
            "product_domain": domain,
            "predicted_risk_score": scored["p_ae_subpopulation"],
            "n_cases": scored["n_ae_in_subpopulation"],
            "mitigation": mitigation,
            "actionable_insight": mitigation["headline"] + " — " + "; ".join(
                mitigation["recommendations"][:2]
            ),
        })

    ranked.sort(
        key=lambda r: (
            1 if r.get("passes_gates") else 0,
            r["risk_elevation_multiplier"],
            r["chi_square_yates"],
            r["n_ae_in_subpopulation"],
        ),
        reverse=True,
    )
    ranked = ranked[:top_n]

    n_pass = sum(1 for r in ranked if r.get("passes_gates"))
    verdict = (
        f"{n_pass} stratum(s) pass REM≥{REM_MIN} & χ²≥{CHI2_MIN} for {product} → {ae} "
        f"(ranked {len(ranked)} of evaluated; n_exposed={n_exp}, baseline P(AE)={baseline:.3f})."
        if ranked
        else f"No subpopulation cleared REM≥{REM_MIN} & χ²≥{CHI2_MIN} for {product} → {ae}."
    )

    return {
        "product_id": product,
        "target_ae_pt": ae,
        "product_domain": domain,
        "method": "risk_elevation_multiplier",
        "formula": "REM = P(AE | Drug ∩ Subpopulation) / P(AE | Drug ∩ General Cohort)",
        "gates": {"rem_min": REM_MIN, "chi2_min": CHI2_MIN, "haldane_anscombe": True},
        "n_drug_exposed": n_exp,
        "n_ae_among_exposed": n_ae,
        "baseline_p_ae": round(baseline, 4),
        "ranked": ranked,
        "findings": ranked,  # Lenses alias
        "segments": ranked,
        "optional_shap_backend": "sklearn+shap" if shap_map else "deterministic_attribution",
        "needs_demo_seed": n_exp < 12,
        "headline": verdict,
        "verdict": verdict,
        "how_to_use": (
            "Ranked strata are ordered by Risk Elevation Multiplier. Open mitigation "
            "recommendations: drugs → Section 5 / Contraindications; devices → engineering "
            "or procedure RCA. Attribution % explains which feature drives the REM excess."
        ),
        "disclaimer": _DISCLAIMER,
        "ontology_stack": _ONTOLOGY_STACK,
        "evidence_sources": [
            "VigilAI AE corpus (demographics + comorbidity cues from narrative NLP)",
            "openFDA FAERS/MAUDE corroboration layer",
            "PubMed / DailyMed evidence enrichment",
        ],
    }
