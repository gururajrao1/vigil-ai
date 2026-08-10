"""Multi-post thread / cohort corroboration scoring (Algo-Pharma inspired).

Given a signal's supporting posts, weigh corroborating AE mentions against
contradicting / negated ones and produce a Confidence + RAG traffic light.
Evidence hierarchy weights (literature > regulatory > social) temper confidence
so social-only cohorts do not over-claim confirmation.

Deterministic, offline, no external deps.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .evidence_hierarchy import tier_weight


def score_thread(posts: List[Dict[str, Any]], drug: str = "", symptom: str = "") -> Dict[str, Any]:
    """Score corroboration across a signal's supporting cohort.

    ``posts`` entries should include ae_flag, sentiment, negation, drugs, symptoms
    when available (ProcessedPost + RawPost derived dicts). Optional ``platform``
    applies evidence-hierarchy weights.
    """
    n = len(posts)
    if n == 0:
        return {
            "confidence": 0.0,
            "rag": "Green",
            "n_posts": 0,
            "corroborating": 0,
            "contradicting": 0,
            "negated": 0,
            "rationale": "No supporting posts",
            "mean_proof_weight": 0.0,
        }

    drug_l = (drug or "").lower()
    symptom_l = (symptom or "").lower()
    corroborating = 0
    contradicting = 0
    negated = 0
    ae_true = 0
    proof_sum = 0.0
    corr_weight = 0.0
    contra_weight = 0.0

    for p in posts:
        w = tier_weight(p.get("platform"))
        proof_sum += w
        ae = bool(p.get("ae_flag"))
        neg = bool(p.get("negation") or p.get("negated"))
        sent = (p.get("sentiment") or "").upper()
        body = (p.get("body") or p.get("title") or "").lower()
        drugs = " ".join(str(x) for x in (p.get("drugs") or [])).lower() + " " + body
        symptoms = " ".join(str(x) for x in (p.get("symptoms") or [])).lower() + " " + body

        mentions_pair = (not drug_l or drug_l in drugs) and (not symptom_l or symptom_l in symptoms)
        if ae:
            ae_true += 1
        if neg:
            negated += 1
            contradicting += 1
            contra_weight += w
        elif ae and mentions_pair and sent in ("NEGATIVE", "NEG", ""):
            corroborating += 1
            corr_weight += w
        elif sent == "POSITIVE" and mentions_pair:
            contradicting += 1
            contra_weight += w
        elif ae:
            corroborating += 1
            corr_weight += w

    mean_proof = proof_sum / n
    # Confidence: corroboration density tempered by contradictions + proof weight
    raw = (corroborating - 0.6 * contradicting) / max(n, 1)
    # Prefer weight-aware corroboration when platforms are present
    if corr_weight + contra_weight > 0:
        raw_w = (corr_weight - 0.6 * contra_weight) / max(proof_sum, 1e-6)
        raw = 0.5 * raw + 0.5 * raw_w
    confidence = max(0.0, min(1.0, 0.35 + 0.55 * raw + 0.1 * min(ae_true / max(n, 1), 1.0)))
    # Social-only cohorts cannot reach "Red" confirmation on volume alone
    if mean_proof < 0.45:
        confidence = min(confidence, 0.62)

    if confidence >= 0.72 and corroborating >= 2 and contradicting <= corroborating // 2 and mean_proof >= 0.5:
        rag = "Red"
    elif confidence >= 0.45 or (ae_true >= 2 and corroborating >= 1):
        rag = "Amber"
    else:
        rag = "Green"

    rationale = (
        f"{corroborating}/{n} posts corroborate {drug or 'drug'}→{symptom or 'event'}; "
        f"{contradicting} contradict/negate; AE-flagged {ae_true}; "
        f"mean proof weight {mean_proof:.2f} (L1 literature > L2 regulatory > L3 social)."
    )
    return {
        "confidence": round(confidence, 3),
        "rag": rag,
        "n_posts": n,
        "corroborating": corroborating,
        "contradicting": contradicting,
        "negated": negated,
        "ae_flagged": ae_true,
        "mean_proof_weight": round(mean_proof, 3),
        "rationale": rationale,
    }
