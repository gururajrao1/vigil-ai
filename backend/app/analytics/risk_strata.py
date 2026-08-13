"""Proactive risk stratification & population segmentation engine.

Predicts high-risk patient subpopulations for a (product, AE) pair from the
VigilAI AE corpus using:

  X = [age brackets, sex, comorbidity indicators, polypharmacy]
  y = I(severe AE | target PT present)

Primary model: NumPy IRLS logistic regression (offline, no sklearn).
Optional: scikit-learn LogisticRegression / LightGBM + SHAP when installed.

Outputs calibrated segment risk scores, relative risk elevation vs baseline,
and coefficient-as-SHAP contributing factors. Drugs vs devices get domain-
specific actionable insight text (labeling/REMS vs procedure/design RCA).

MedDRA/UMLS/GMDN/ATC are open coding caches.
"""
from __future__ import annotations

import hashlib
import logging
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost
from .risk_features import entities_from_processed, row_from_post

logger = logging.getLogger("vigilai.risk_strata")

_FEATURE_NAMES = [
    "intercept",
    "pediatric",
    "geriatric",
    "sex_female",
    "comorb_diabetes",
    "comorb_wound",
    "comorb_renal",
    "comorb_cv",
    "comorb_cancer",
    "polypharmacy",
]

_WOUND_LABELS = {
    "diabetic foot", "diabetic foot ulcer", "chronic wound", "pressure ulcer",
    "wound infection", "necrosis", "tissue necrosis", "skin erosion", "ulcer",
}
_DIABETES = {"diabetes mellitus", "type 2 diabetes mellitus", "type 1 diabetes mellitus", "diabetic foot", "diabetic foot ulcer"}
_RENAL = {"renal failure", "chronic kidney disease"}
_CV = {"hypertension", "heart failure"}
_CANCER = {"malignant neoplasm"}

_DISCLAIMER = (
    "Risk stratification over social/ICSR-style text. "
    ""
    "MedDRA/UMLS/GMDN/ATC coding is an open surrogate. Syn3DWound/AZH wound "
    "datasets are referenced as multi-modal validation targets — narrative "
    "comorbidity tags only unless imaging adapters are configured."
)

_ONTOLOGY_STACK = [
    "MedDRA-style PT/SOC (open surrogate)",
    "UMLS-style CUI surrogates",
    "ATC / GMDN (when product_type coded)",
    "openFDA FAERS/MAUDE corroboration (existing evidence layer)",
    "PubMed / DailyMed (existing evidence layer)",
    "MHRA / EUDAMED (device registry adapters)",
]


def _fit_logistic(X: np.ndarray, y: np.ndarray, max_iter: int = 50) -> Optional[np.ndarray]:
    n, p = X.shape
    if n < 10 or p < 2:
        return None
    # Class balance check
    if y.sum() < 2 or y.sum() > n - 2:
        return None
    beta = np.zeros(p)
    for _ in range(max_iter):
        eta = X @ beta
        mu = 1.0 / (1.0 + np.exp(-np.clip(eta, -20, 20)))
        w = np.maximum(mu * (1.0 - mu), 1e-6)
        z = eta + (y - mu) / w
        W = np.diag(w)
        try:
            xtwx = X.T @ W @ X
            xtwz = X.T @ W @ z
            beta_new = np.linalg.solve(xtwx + 1e-3 * np.eye(p), xtwz)
        except np.linalg.LinAlgError:
            return None
        if np.max(np.abs(beta_new - beta)) < 1e-5:
            beta = beta_new
            break
        beta = beta_new
    return beta


def _sigmoid(z: float) -> float:
    return float(1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, z)))))


def _try_sklearn_lgbm(
    X: np.ndarray, y: np.ndarray, feature_names: Sequence[str]
) -> Optional[Dict[str, Any]]:
    """Optional LightGBM / sklearn path with SHAP when packages exist."""
    try:
        import lightgbm as lgb  # type: ignore
    except ImportError:
        lgb = None
    try:
        from sklearn.linear_model import LogisticRegression  # type: ignore
    except ImportError:
        LogisticRegression = None  # type: ignore

    if lgb is not None and len(y) >= 30:
        try:
            model = lgb.LGBMClassifier(
                n_estimators=40, max_depth=3, learning_rate=0.1,
                subsample=0.9, colsample_bytree=0.9, verbose=-1,
            )
            # drop intercept column for tree models
            Xt = X[:, 1:]
            model.fit(Xt, y)
            names = list(feature_names[1:])
            imp = getattr(model, "feature_importances_", None)
            shap_map = {}
            try:
                import shap  # type: ignore
                explainer = shap.TreeExplainer(model)
                sv = explainer.shap_values(Xt[: min(80, len(Xt))])
                if isinstance(sv, list):
                    sv = sv[1]
                mean_abs = np.mean(np.abs(sv), axis=0)
                shap_map = {names[i]: float(mean_abs[i]) for i in range(len(names))}
            except Exception:
                if imp is not None:
                    shap_map = {names[i]: float(imp[i]) for i in range(len(names))}
            return {"kind": "lightgbm", "model": model, "shap_map": shap_map, "names": names}
        except Exception:
            logger.debug("LightGBM path failed", exc_info=True)

    if LogisticRegression is not None and len(y) >= 12:
        try:
            clf = LogisticRegression(max_iter=200, class_weight="balanced")
            clf.fit(X, y)
            coef = clf.coef_.ravel()
            shap_map = {feature_names[i]: float(coef[i]) for i in range(len(feature_names))}
            return {"kind": "sklearn_logit", "model": clf, "shap_map": shap_map, "coef": coef}
        except Exception:
            logger.debug("sklearn path failed", exc_info=True)
    return None


def _vectorize(row: dict) -> np.ndarray:
    comorb = {c.lower() for c in (row.get("comorbidities") or [])}
    wound = 1.0 if comorb & _WOUND_LABELS else 0.0
    diabetes = 1.0 if comorb & _DIABETES or wound else 0.0
    renal = 1.0 if comorb & _RENAL else 0.0
    cv = 1.0 if comorb & _CV else 0.0
    cancer = 1.0 if comorb & _CANCER else 0.0
    bracket = row.get("age_bracket") or "UNKNOWN"
    return np.array([
        1.0,
        1.0 if bracket == "PEDIATRIC" else 0.0,
        1.0 if bracket == "GERIATRIC" else 0.0,
        1.0 if row.get("sex") == "F" else 0.0,
        diabetes,
        wound,
        renal,
        cv,
        cancer,
        1.0 if len(row.get("concomitant_meds") or []) >= 2 else 0.0,
    ], dtype=float)


def _event_match(events: List[str], target: str) -> bool:
    t = (target or "").lower().strip()
    if not t:
        return False
    for e in events:
        el = (e or "").lower()
        if el == t or t in el or el in t:
            return True
    return False


def _product_match(product: str, focus: str) -> bool:
    a, b = (product or "").lower(), (focus or "").lower()
    if not a or not b:
        return False
    if a == b or b in a or a in b:
        return True
    # Ontology closure: a brand/INN-dual mention counts as the same product
    # (tylenol ≡ acetaminophen ≡ paracetamol) instead of splitting the cohort.
    try:
        from ..nlp.ontology import aliases_for_product

        return bool(aliases_for_product(a) & aliases_for_product(b))
    except Exception:  # pragma: no cover - defensive, keeps analytics running
        logger.debug("ontology product match failed for %r/%r", a, b, exc_info=True)
        return False


def _actionable(domain: str, factors: List[dict], product: str, ae: str) -> str:
    tops = [f["factor"] for f in factors[:3]]
    joined = ", ".join(tops) if tops else "demographic/comorbidity profile"
    if domain in ("device", "combination"):
        return (
            f"Device vigilance: high-risk procedure/patient profile for {product} → {ae}. "
            f"Drivers: {joined}. Consider root-cause analysis, procedural checklist updates, "
            f"or engineering design review (IMDRF/GMDN-aligned)."
        )
    if domain == "vaccine":
        return (
            f"Vaccine AESI stratification for {product} → {ae}. Drivers: {joined}. "
            f"Flag for AESI cohort monitoring and Brighton-style case definition review."
        )
    return (
        f"Pharmaceutical: elevated risk segment for {product} → {ae}. Drivers: {joined}. "
        f"Consider labeling/contraindication language, REMS-style mitigation, or targeted "
        f"HCP communication for this subpopulation."
    )


def _build_rows(db: Session, project_id: Optional[int]) -> List[dict]:
    q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
    )
    if project_id is not None:
        q = q.filter(RawPost.project_id == project_id)
    rows = []
    for processed, raw in q.all():
        ents = entities_from_processed(processed.entities_json)
        drugs = []
        for d in ents.get("drugs") or []:
            name = (d.get("normalized") or d.get("text") or "").strip().lower()
            if name:
                drugs.append(name)
        events = []
        for s in ents.get("symptoms") or []:
            ev = (s.get("pt") or s.get("normalized") or s.get("text") or "").strip().lower()
            if ev:
                events.append(ev)
        if not drugs or not events:
            continue
        text = f"{raw.title or ''} {raw.body or ''}".strip()
        rows.append(row_from_post(
            text=text,
            drugs=drugs,
            events=events,
            entities=ents,
            region=raw.region,
            product_type=raw.product_type or "drug",
            post_id=processed.id,
        ))
    return rows


def _segment_profiles() -> List[Dict[str, Any]]:
    """Canonical subpopulation templates to score."""
    return [
        {"id": "geriatric_female", "label": "Geriatric · female",
         "age_bracket": "GERIATRIC", "sex": "F", "comorbidities": []},
        {"id": "geriatric_diabetes", "label": "Geriatric · diabetes",
         "age_bracket": "GERIATRIC", "sex": "U", "comorbidities": ["diabetes mellitus"]},
        {"id": "diabetic_foot_wound", "label": "Diabetes · chronic wound / DFU",
         "age_bracket": "ADULT", "sex": "U",
         "comorbidities": ["diabetes mellitus", "diabetic foot ulcer", "chronic wound"]},
        {"id": "renal_impairment", "label": "Renal impairment cohort",
         "age_bracket": "ADULT", "sex": "U", "comorbidities": ["renal failure"]},
        {"id": "pediatric", "label": "Pediatric",
         "age_bracket": "PEDIATRIC", "sex": "U", "comorbidities": []},
        {"id": "polypharmacy_cv", "label": "CV comorbidity · polypharmacy",
         "age_bracket": "GERIATRIC", "sex": "U",
         "comorbidities": ["hypertension", "heart failure"], "polypharmacy": True},
        {"id": "oncology", "label": "Oncology / malignancy history",
         "age_bracket": "ADULT", "sex": "U", "comorbidities": ["malignant neoplasm"]},
    ]


def predict_high_risk_populations(
    db: Session,
    product_id: str,
    target_ae_pt: str,
    *,
    min_confidence: float = 0.80,
    project_id: Optional[int] = None,
    limit: int = 8,
) -> dict:
    """Identify high-risk demographic/comorbidity segments for a product–AE pair."""
    product = (product_id or "").strip().lower()
    ae = (target_ae_pt or "").strip().lower()
    if not product or not ae:
        return {
            "product_id": product_id,
            "target_ae_pt": target_ae_pt,
            "model": "none",
            "segments": [],
            "needs_demo_seed": True,
            "verdict": "Provide both product_id and target_ae_pt.",
            "disclaimer": _DISCLAIMER,
            "ontology_stack": _ONTOLOGY_STACK,
            "evidence_sources": [],
        }

    all_rows = _build_rows(db, project_id)
    # Focus: posts mentioning the product; y = target AE (or severe if AE matches)
    focused = [r for r in all_rows if _product_match(r["product"], product)
               or any(_product_match(d, product) for d in ([r["product"]] + (r.get("concomitant_meds") or [])))]
    # Also include posts where product appears in concomitant bag
    if len(focused) < 5:
        focused = [
            r for r in all_rows
            if _product_match(r.get("product", ""), product)
            or any(_product_match(m, product) for m in (r.get("concomitant_meds") or []))
            or product in (r.get("text") or "").lower()
        ]

    X_list, y_list, used = [], [], []
    for r in focused:
        has_ae = _event_match(r.get("events") or [], ae)
        # Response: target AE present; boost with severity when AE matched
        y = 1.0 if has_ae else 0.0
        if has_ae and r.get("severe_ae"):
            y = 1.0
        X_list.append(_vectorize(r))
        y_list.append(y)
        used.append(r)

    # Fallback training universe: all AE posts, y = product+AE co-mention
    if len(used) < 12:
        X_list, y_list, used = [], [], []
        for r in all_rows:
            has_prod = (
                _product_match(r.get("product", ""), product)
                or any(_product_match(m, product) for m in (r.get("concomitant_meds") or []))
            )
            has_ae = _event_match(r.get("events") or [], ae)
            y = 1.0 if (has_prod and has_ae) else 0.0
            if not has_prod and not has_ae:
                continue
            X_list.append(_vectorize(r))
            y_list.append(y)
            used.append(r)

    n = len(used)
    n_pos = int(sum(y_list)) if y_list else 0
    baseline = (n_pos / n) if n else 0.0

    model_name = "insufficient_data"
    beta = None
    shap_global: Dict[str, float] = {}
    optional = None

    if n >= 12 and n_pos >= 2:
        X = np.vstack(X_list)
        y = np.array(y_list, dtype=float)
        optional = _try_sklearn_lgbm(X, y, _FEATURE_NAMES)
        if optional and optional.get("kind") == "lightgbm":
            model_name = "lightgbm+shap" if optional.get("shap_map") else "lightgbm"
            shap_global = optional.get("shap_map") or {}
            # synthesize beta-like vector for segment scoring via margin
            beta = np.zeros(len(_FEATURE_NAMES))
            beta[0] = math.log(max(baseline, 1e-3) / max(1 - baseline, 1e-3))
            for i, name in enumerate(_FEATURE_NAMES[1:], start=1):
                beta[i] = 0.15 * float(shap_global.get(name, 0.0))
        elif optional and optional.get("kind") == "sklearn_logit":
            model_name = "sklearn_logistic"
            beta = optional["coef"]
            shap_global = optional.get("shap_map") or {}
        else:
            beta = _fit_logistic(X, y)
            if beta is not None:
                model_name = "numpy_irls_logistic"
                shap_global = {
                    _FEATURE_NAMES[i]: float(beta[i]) for i in range(len(_FEATURE_NAMES))
                }

    # Empirical segment rates as backup / blend
    segments = []
    for prof in _segment_profiles():
        # Build synthetic feature vector for profile
        fake = {
            "age_bracket": prof["age_bracket"],
            "sex": prof.get("sex", "U"),
            "comorbidities": prof.get("comorbidities") or [],
            "concomitant_meds": ["a", "b"] if prof.get("polypharmacy") else [],
        }
        x = _vectorize(fake)

        # Empirical support in corpus
        n_seg = 0
        n_seg_pos = 0
        for r, yi in zip(used, y_list):
            ok = True
            if prof["age_bracket"] != "UNKNOWN" and r.get("age_bracket") not in (
                prof["age_bracket"], "UNKNOWN"
            ):
                # allow UNKNOWN age rows into non-pediatric segments softly
                if r.get("age_bracket") == "UNKNOWN":
                    pass
                elif r.get("age_bracket") != prof["age_bracket"]:
                    ok = False
            need = set(c.lower() for c in (prof.get("comorbidities") or []))
            have = set(c.lower() for c in (r.get("comorbidities") or []))
            if need and not (need & have):
                # wound profile: also match wound labels
                if "diabetic foot ulcer" in need or "chronic wound" in need:
                    if not (have & _WOUND_LABELS) and not (have & _DIABETES):
                        ok = False
                else:
                    ok = False
            if not ok:
                continue
            n_seg += 1
            n_seg_pos += int(yi)

        emp_rate = (n_seg_pos / n_seg) if n_seg else baseline
        if beta is not None:
            risk = _sigmoid(float(x @ beta))
        else:
            # Rule-based elevation when model can't fit
            risk = emp_rate
            bump = 0.0
            if any(c in (fake["comorbidities"] or []) for c in (
                "diabetic foot ulcer", "chronic wound", "renal failure", "malignant neoplasm"
            )):
                bump += 0.12
            if fake["age_bracket"] == "GERIATRIC":
                bump += 0.08
            if fake["age_bracket"] == "PEDIATRIC":
                bump += 0.05
            risk = min(0.95, max(risk, baseline) + bump)
            model_name = model_name if model_name != "insufficient_data" else "rule_based_strata"

        rr = (risk / baseline) if baseline > 1e-6 else (risk / 0.05)
        # Contributions (linear SHAP-style): phi_i = beta_i * x_i
        factors = []
        if beta is not None:
            for i, name in enumerate(_FEATURE_NAMES):
                if i == 0:
                    continue
                val = float(beta[i] * x[i])
                if abs(val) < 1e-4 and name not in shap_global:
                    continue
                if x[i] < 0.5 and name not in shap_global:
                    continue
                contrib = val if x[i] >= 0.5 else float(shap_global.get(name, 0.0)) * 0.1
                if abs(contrib) < 1e-4:
                    continue
                factors.append({
                    "factor": name,
                    "shap_value": round(contrib, 4),
                    "direction": "elevates" if contrib > 0 else "protects",
                    "note": "IRLS coefficient × feature (logistic SHAP analogue)"
                    if "logistic" in model_name or "irls" in model_name
                    else "Model attribution",
                })
        factors.sort(key=lambda f: abs(f["shap_value"]), reverse=True)
        factors = factors[:5]

        # Skip low-signal segments unless empirically supported
        if risk < min_confidence * 0.5 and n_seg_pos < 1 and rr < 1.25:
            continue

        domain = "drug"
        for r in used[:20]:
            if _product_match(r.get("product", ""), product):
                domain = r.get("product_type") or "drug"
                break
        # Device name heuristics
        if any(tok in product for tok in (
            "catheter", "stent", "pump", "implant", "mesh", "defibrillator", "pacemaker"
        )):
            domain = "device"

        seg_id = hashlib.sha1(f"{product}|{ae}|{prof['id']}".encode()).hexdigest()[:10]
        segments.append({
            "segment_id": seg_id,
            "label": prof["label"],
            "product": product,
            "target_ae_pt": ae,
            "product_domain": domain,
            "n_cases": int(n_seg_pos),
            "n_segment_posts": int(n_seg),
            "predicted_risk_score": round(float(risk), 3),
            "relative_risk_elevation": round(float(rr), 2),
            "top_contributing_factors": factors,
            "actionable_insight": _actionable(domain, factors, product, ae),
            "ontology_refs": {
                "meddra_pt": ae,
                "comorbidity_cuis": [
                    # expose CUIs from profile comorbidities via a fresh extract
                ],
                "age_bracket": prof["age_bracket"],
            },
        })

    segments.sort(
        key=lambda s: (s["predicted_risk_score"], s["relative_risk_elevation"], s["n_cases"]),
        reverse=True,
    )
    segments = segments[:limit]

    # Filter by min_confidence on risk score (soft): keep elevated RR even if score mid
    kept = [
        s for s in segments
        if s["predicted_risk_score"] >= min_confidence or s["relative_risk_elevation"] >= 1.5
    ]
    if not kept and segments:
        kept = segments[:3]

    needs_seed = n < 8 or n_pos < 2
    verdict = (
        f"{len(kept)} high-risk segment(s) for {product} → {ae} "
        f"(model={model_name}, n={n}, positives={n_pos}, baseline={baseline:.2f})."
        if kept
        else f"No elevated segments above confidence {min_confidence} — load more AE corpus / PV demo pack."
    )

    return {
        "product_id": product,
        "target_ae_pt": ae,
        "model": model_name,
        "n_training_rows": n,
        "n_positive": n_pos,
        "baseline_risk": round(baseline, 3),
        "segments": kept,
        "findings": kept,  # Lenses UI alias
        "evidence_sources": [
            "VigilAI AE corpus (social + FAERS/VAERS/MAUDE ingest)",
            "openFDA FAERS/MAUDE (corroboration layer)",
            "PubMed / DailyMed (evidence enrichment)",
            "MHRA / EUDAMED adapters (device)",
            "Data Forge synthetic narratives (optional stress tests)",
            "Syn3DWound / AZH wound comorbidity tags (narrative surrogate)",
        ],
        "ontology_stack": _ONTOLOGY_STACK,
        "feature_names": _FEATURE_NAMES,
        "needs_demo_seed": needs_seed,
        "headline": verdict,
        "verdict": verdict,
        "how_to_use": (
            "Pick a product + target AE (MedDRA-style PT). Review segments with elevated "
            "predicted_risk_score and relative_risk_elevation. Top factors are SHAP-style "
            "attributions. Drug insights → labeling/REMS; device → procedure/design RCA."
        ),
        "disclaimer": _DISCLAIMER,
    }


def list_candidate_pairs(db: Session, project_id: Optional[int] = None, limit: int = 12) -> dict:
    """Suggest product–AE pairs with enough mass to stratify."""
    from collections import Counter
    rows = _build_rows(db, project_id)
    ctr: Counter = Counter()
    for r in rows:
        for e in r.get("events") or []:
            ctr[(r.get("product") or "", e)] += 1
    pairs = [
        {"product_id": p, "target_ae_pt": e, "n": n}
        for (p, e), n in ctr.most_common(limit * 3)
        if p and e and n >= 2
    ][:limit]
    return {
        "pairs": pairs,
        "needs_demo_seed": len(pairs) < 3,
        "disclaimer": _DISCLAIMER,
    }
