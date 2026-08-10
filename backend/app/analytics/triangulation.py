"""Multi-source signal triangulation matrix (GVP Module 3).

Pillars: Social/News DMA · Regulatory (FAERS/MAUDE) · RWD (OMOP/MIMIC surrogate).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("vigilai.triangulation")

_DISCLAIMER = (
    "Prototype triangulation over social DMA, openFDA surrogates, and OMOP staging. "
    "Not a validated multi-database epidemiology study; not for clinical use."
)


def _safe_json(raw, default=None):
    if default is None:
        default = {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}") or default
    except Exception:
        return default


def _pillar_social(sig: dict) -> dict:
    prr = float(sig.get("prr") or 0.0)
    chi2 = float(sig.get("chi_square") or sig.get("chi2") or 0.0)
    n = int(sig.get("a") or sig.get("count") or sig.get("n_cases") or 0)
    strength = (sig.get("strength") or "").upper()
    passed = strength == "STRONG" or (prr >= 2.0 and chi2 >= 4.0 and n >= 3)
    score = 0.0
    if passed:
        score = min(1.0, 0.45 + 0.15 * min(prr / 5.0, 1.0) + 0.2 * (1.0 if strength == "STRONG" else 0.5))
    elif prr >= 1.5 and n >= 2:
        score = 0.35
    elif n >= 1:
        score = 0.15
    return {
        "pillar": "social",
        "label": "Unstructured Social / News",
        "passed": passed,
        "score": round(score, 3),
        "metrics": {"prr": prr, "chi_square": chi2, "n": n, "strength": strength or "WEAK"},
    }


def _pillar_regulatory(sig: dict) -> dict:
    fda = _safe_json(sig.get("fda_evidence"), {})
    known = bool(fda.get("known") or fda.get("drug_event_known") or fda.get("matched"))
    count = int(fda.get("count") or fda.get("faers_count") or fda.get("total") or 0)
    maude = bool(fda.get("maude") or fda.get("device_known"))
    # Also honor label / openFDA corroboration flags on the signal
    if sig.get("openfda_known"):
        known = True
    passed = known or count >= 3 or maude
    score = 0.0
    if known and count >= 10:
        score = 0.95
    elif known or count >= 3:
        score = 0.75
    elif count >= 1:
        score = 0.4
    elif maude:
        score = 0.7
    return {
        "pillar": "regulatory",
        "label": "Spontaneous Regulatory (FAERS / MAUDE)",
        "passed": passed,
        "score": round(score, 3),
        "metrics": {"known": known, "faers_count": count, "maude": maude},
    }


def _pillar_rwd(db: Optional[Session], product: str, event: str) -> dict:
    """OMOP staging co-occurrence or MIMIC-style fixture rates."""
    n_support = 0
    source = "none"
    if db is not None:
        try:
            from ..db.schemas.omop_cdm import OmopConditionOccurrence, OmopDrugExposure

            drugs = (
                db.query(OmopDrugExposure)
                .filter(OmopDrugExposure.drug_source_value.ilike(f"%{(product or '')[:40]}%"))
                .limit(500)
                .all()
            )
            if drugs:
                person_ids = {d.person_id for d in drugs if d.person_id is not None}
                if person_ids:
                    conds = (
                        db.query(OmopConditionOccurrence)
                        .filter(OmopConditionOccurrence.person_id.in_(list(person_ids)[:200]))
                        .filter(
                            OmopConditionOccurrence.condition_source_value.ilike(
                                f"%{(event or '')[:40]}%"
                            )
                        )
                        .limit(100)
                        .all()
                    )
                    n_support = len(conds)
                    source = "omop_staging"
        except Exception:
            logger.debug("OMOP RWD pillar failed", exc_info=True)

    # Offline MIMIC-style fixture for demo products when OMOP empty
    if n_support == 0:
        fixture = {
            ("isotretinoin", "depression"): 8,
            ("warfarin", "haemorrhage"): 12,
            ("warfarin", "hemorrhage"): 12,
            ("ibuprofen", "renal failure"): 5,
            ("clozapine", "myocarditis"): 4,
            ("semaglutide", "pancreatitis"): 3,
        }
        key = ((product or "").lower(), (event or "").lower())
        # fuzzy: substring
        for (p, e), n in fixture.items():
            if p in key[0] or key[0] in p:
                if e in key[1] or key[1] in e:
                    n_support = n
                    source = "mimic_style_fixture"
                    break

    passed = n_support >= 3
    score = min(1.0, n_support / 10.0) if n_support else 0.0
    return {
        "pillar": "rwd",
        "label": "Real-World Data (OMOP / MIMIC surrogate)",
        "passed": passed,
        "score": round(score, 3),
        "metrics": {"n_support": n_support, "source": source},
    }


def _tier(social: dict, regulatory: dict, rwd: dict) -> str:
    s, r, w = social["passed"], regulatory["passed"], rwd["passed"]
    if s and r and w:
        return "CRITICAL_URGENT"
    if s and r:
        return "HIGH_EARLY_WARNING"
    if s and not r and not w:
        return "EMERGENT_CHATTER"
    if r and not s:
        return "REGULATORY_ONLY"
    return "INSUFFICIENT"


def triangulate_signal(
    sig: dict,
    *,
    db: Optional[Session] = None,
) -> dict:
    """Compute multi-pillar triangulation for one signal dict."""
    product = sig.get("drug") or sig.get("product") or ""
    event = sig.get("meddra_pt") or sig.get("symptom") or ""

    social = _pillar_social(sig)
    regulatory = _pillar_regulatory(sig)
    rwd = _pillar_rwd(db, product, event)

    pillars = [social, regulatory, rwd]
    n_pass = sum(1 for p in pillars if p["passed"])
    # Weighted score: social 0.35, regulatory 0.40, rwd 0.25
    tri = (
        0.35 * social["score"]
        + 0.40 * regulatory["score"]
        + 0.25 * rwd["score"]
    )
    # Boost when all three fire
    if n_pass == 3:
        tri = min(1.0, tri + 0.12)

    urgency = _tier(social, regulatory, rwd)
    badge = {
        "CRITICAL_URGENT": "CRITICAL URGENT — TRIANGULATED",
        "HIGH_EARLY_WARNING": "HIGH EARLY WARNING",
        "EMERGENT_CHATTER": "EMERGENT CHATTER",
        "REGULATORY_ONLY": "REGULATORY ONLY",
        "INSUFFICIENT": "INSUFFICIENT TRIANGULATION",
    }.get(urgency, urgency)

    return {
        "product": (product or "").lower(),
        "event": (event or "").lower(),
        "pillars": pillars,
        "n_pillars_passed": n_pass,
        "triangulated_risk_score": round(float(tri), 3),
        "urgency_tier": urgency,
        "badge": badge,
        "disclaimer": _DISCLAIMER,
    }


def triangulate_signal_row(db: Session, signal_row) -> dict:
    """Build triangulation from an ORM Signal (+ helpers shape)."""
    from ..api.helpers import signal_to_dict

    return triangulate_signal(signal_to_dict(signal_row, fda=True), db=db)
