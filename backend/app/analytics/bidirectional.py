"""Bi-directional product ↔ adverse-event analytics for clinical cross-section views."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Signal
from ..nlp.drug_norm import canonical_product
from ..nlp.text_normalize import fold_key, normalize_label


SEVERITY_TIERS = ("Critical", "High", "Moderate", "Mild")

# Signal.severity uses Critical/High/Medium/Low — map to API tier vocabulary
_SEVERITY_ALIAS = {
    "Critical": "Critical",
    "High": "High",
    "Medium": "Moderate",
    "Moderate": "Moderate",
    "Low": "Mild",
    "Mild": "Mild",
}


def _severity_bucket(sig: Signal) -> str:
    """Map signal severity / strength into the four visual tiers."""
    sev = (sig.severity or "").strip()
    if sev in _SEVERITY_ALIAS:
        return _SEVERITY_ALIAS[sev]
    strength = (sig.strength or "WEAK").upper()
    if strength == "STRONG":
        return "High"
    if strength == "MODERATE":
        return "Moderate"
    return "Mild"


def _legacy_project(col, project_id: Optional[int]):
    from sqlalchemy import or_

    if project_id is None:
        return True
    return or_(col == project_id, col.is_(None), col == 0)


def _signal_row(sig: Signal) -> dict[str, Any]:
    return {
        "id": sig.id,
        "drug": sig.drug,
        "symptom": sig.meddra_pt or sig.symptom,
        "meddra_pt": sig.meddra_pt,
        "meddra_soc": sig.meddra_soc,
        "prr": float(sig.prr or 0),
        "ror": float(sig.ror or 0) if sig.ror is not None else None,
        "chi_square": float(sig.chi_square or 0) if sig.chi_square is not None else None,
        "ic025": float(sig.ic025) if sig.ic025 is not None else None,
        "eb05": float(sig.eb05) if sig.eb05 is not None else None,
        "strength": sig.strength,
        "severity": sig.severity,
        "tier": _severity_bucket(sig),
        "post_count": sig.post_count or 0,
        "spike_flag": bool(sig.spike_flag),
        "sdr_flag": bool(getattr(sig, "sdr_flag", False)),
    }


def _match_drug(sig: Signal, want: str) -> bool:
    a = fold_key(sig.drug or "")
    b = fold_key(want)
    if not a or not b:
        return False
    if a == b:
        return True
    # substring for partial UI selections
    return b in a or a in b


def _match_event(sig: Signal, want: str) -> bool:
    labels = [sig.meddra_pt or "", sig.symptom or ""]
    b = fold_key(want)
    if not b:
        return False
    for lab in labels:
        a = fold_key(lab)
        if a and (a == b or b in a or a in b):
            return True
    return False


def drug_to_events(
    db: Session,
    drug_name: str,
    *,
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    """Forward path: product → adverse events, bucketed by severity tier."""
    want = normalize_label(drug_name, kind="product") or drug_name
    canon = canonical_product(want) or want

    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(_legacy_project(Signal.project_id, project_id))

    matched = [s for s in q.all() if _match_drug(s, canon) or _match_drug(s, drug_name)]
    tiers: dict[str, list] = {t: [] for t in SEVERITY_TIERS}
    for s in matched:
        tiers[_severity_bucket(s)].append(_signal_row(s))

    for t in SEVERITY_TIERS:
        tiers[t].sort(key=lambda r: (r.get("prr") or 0), reverse=True)

    return {
        "drug": canon,
        "query": drug_name,
        "total": len(matched),
        "tiers": tiers,
        "events": sorted(
            (_signal_row(s) for s in matched),
            key=lambda r: (r.get("prr") or 0),
            reverse=True,
        ),
    }


def event_to_drugs(
    db: Session,
    event_name: str,
    *,
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    """Inverse path: adverse event → products, ordered by PRR then ROR."""
    want = normalize_label(event_name, kind="event") or event_name

    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(_legacy_project(Signal.project_id, project_id))

    matched = [s for s in q.all() if _match_event(s, want) or _match_event(s, event_name)]
    # Deduplicate by drug — keep strongest PRR row
    by_drug: dict[str, Signal] = {}
    for s in matched:
        key = (s.drug or "").lower()
        prev = by_drug.get(key)
        if prev is None or float(s.prr or 0) >= float(prev.prr or 0):
            by_drug[key] = s

    rows = [_signal_row(s) for s in by_drug.values()]
    rows.sort(
        key=lambda r: (r.get("prr") or 0, r.get("ror") or 0, r.get("post_count") or 0),
        reverse=True,
    )

    return {
        "event": want,
        "query": event_name,
        "total": len(rows),
        "drugs": rows,
    }
