"""Indication / age / co-prescription confounding adjustment via logistic regression.

Fits a simple IRLS logistic model on AE-flagged posts to estimate the adjusted
odds of the target event for drug A vs drug B while controlling for indication
proxy (co-reported conditions), age-band (when present), and concurrent product
noise. Pure NumPy — no scikit-learn dependency. Offline and deterministic.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Optional

import numpy as np
from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost

logger = logging.getLogger("vigilai.confounding")


def _age_band(entities: dict) -> str:
    demo = entities.get("demographics") or entities.get("patient") or {}
    age = demo.get("age") or demo.get("age_years")
    try:
        age = float(age)
    except (TypeError, ValueError):
        return "unknown"
    if age < 18:
        return "pediatric"
    if age < 45:
        return "adult"
    if age < 65:
        return "middle"
    return "elderly"


def _fit_logistic(X: np.ndarray, y: np.ndarray, max_iter: int = 40) -> Optional[np.ndarray]:
    """IRLS logistic regression; returns coefficient vector or None."""
    n, p = X.shape
    if n < 8 or p < 2:
        return None
    beta = np.zeros(p)
    for _ in range(max_iter):
        eta = X @ beta
        # numerically stable sigmoid
        mu = 1.0 / (1.0 + np.exp(-np.clip(eta, -20, 20)))
        w = mu * (1.0 - mu)
        w = np.maximum(w, 1e-6)
        z = eta + (y - mu) / w
        W = np.diag(w)
        try:
            xtwx = X.T @ W @ X
            xtwz = X.T @ W @ z
            beta_new = np.linalg.solve(xtwx + 1e-4 * np.eye(p), xtwz)
        except np.linalg.LinAlgError:
            return None
        if np.max(np.abs(beta_new - beta)) < 1e-5:
            beta = beta_new
            break
        beta = beta_new
    return beta


def adjust_pair_for_confounding(
    db: Session,
    drug_a: str,
    drug_b: str,
    event: str,
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    """Compare adjusted log-odds of `event` for drug_a vs drug_b.

    Design matrix columns:
      [intercept, drug_a, indication_proxy, age_adult, age_middle, age_elderly, polypharmacy]
    Outcome y = 1 if event PT/symptom present in the post.
    """
    q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
    )
    if project_id is not None:
        from sqlalchemy import or_

        q = q.filter(or_(RawPost.project_id == project_id, RawPost.project_id.is_(None), RawPost.project_id == 0))

    rows_x: list[list[float]] = []
    rows_y: list[float] = []
    event_l = event.lower()
    a_l = drug_a.lower()
    b_l = drug_b.lower()

    for proc, _raw in q.limit(4000).all():
        try:
            ent = json.loads(proc.entities_json or "{}")
        except json.JSONDecodeError:
            continue
        drugs = [d.get("normalized", "").lower() for d in ent.get("drugs", []) if d.get("normalized")]
        symptoms = [s.get("normalized", "").lower() for s in ent.get("symptoms", []) if s.get("normalized")]
        conditions = [c.get("normalized", "").lower() for c in ent.get("conditions", []) if c.get("normalized")]

        has_a = a_l in drugs
        has_b = b_l in drugs
        if not (has_a or has_b):
            continue

        y = 1.0 if any(event_l in s or s in event_l for s in symptoms) else 0.0
        age = _age_band(ent)
        indication = 1.0 if conditions else 0.0
        poly = 1.0 if len(drugs) >= 2 else 0.0
        rows_x.append([
            1.0,
            1.0 if has_a else 0.0,
            indication,
            1.0 if age == "adult" else 0.0,
            1.0 if age == "middle" else 0.0,
            1.0 if age == "elderly" else 0.0,
            poly,
        ])
        rows_y.append(y)

    n = len(rows_y)
    if n < 12:
        return {
            "adjusted": False,
            "reason": "insufficient_paired_reports",
            "n": n,
            "note": "Need ≥12 AE posts mentioning either drug for IRLS logistic fit.",
        }

    X = np.asarray(rows_x, dtype=float)
    y = np.asarray(rows_y, dtype=float)
    beta = _fit_logistic(X, y)
    if beta is None:
        return {"adjusted": False, "reason": "singular_design", "n": n}

    # Coefficient on drug_a indicator ≈ log-odds vs drug_b-only baseline in this subset
    coef_a = float(beta[1])
    or_adj = math.exp(coef_a)
    # Crude OR from 2x2 within the same subset
    a_event = sum(1 for i, r in enumerate(rows_x) if r[1] == 1 and rows_y[i] == 1)
    a_none = sum(1 for i, r in enumerate(rows_x) if r[1] == 1 and rows_y[i] == 0)
    b_event = sum(1 for i, r in enumerate(rows_x) if r[1] == 0 and rows_y[i] == 1)
    b_none = sum(1 for i, r in enumerate(rows_x) if r[1] == 0 and rows_y[i] == 0)
    crude_or = ((a_event + 0.5) * (b_none + 0.5)) / ((a_none + 0.5) * (b_event + 0.5))

    return {
        "adjusted": True,
        "n": n,
        "method": "logistic_irls",
        "covariates": [
            "intercept",
            f"drug={drug_a}",
            "indication_proxy",
            "age_adult",
            "age_middle",
            "age_elderly",
            "polypharmacy",
        ],
        "coefficients": [round(float(c), 4) for c in beta.tolist()],
        "adjusted_or_a_vs_b": round(or_adj, 3),
        "crude_or_a_vs_b": round(float(crude_or), 3),
        "spuriousness_delta": round(float(or_adj - crude_or), 3),
        "interpretation": (
            f"Adjusted OR for {event} with {drug_a} vs {drug_b} is {or_adj:.2f} "
            f"(crude {crude_or:.2f}); delta {or_adj - crude_or:+.2f} after indication/age/polypharmacy control."
        ),
    }
