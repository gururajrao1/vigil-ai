"""Longitudinal signal casefile — weekly DMA snapshots + trajectory labels.

Persists PRR / IC025 / EB05 / post_count over time so Signal Detail can show
new vs strengthening vs weakening trajectories (VigiLens-style memory).

Heuristic label-change likelihood is clearly labeled as non-regulatory.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from ..models import Signal, SignalSnapshot


def _week_start(dt: Optional[datetime] = None) -> datetime:
    d = (dt or datetime.utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())  # Monday-start ISO week


def snapshot_signals(db: Session, signals: List[Signal], project_id: Optional[int] = None) -> int:
    """Upsert one snapshot row per signal for the current ISO week. Returns count written."""
    week = _week_start()
    n = 0
    for sig in signals:
        existing = (
            db.query(SignalSnapshot)
            .filter(
                SignalSnapshot.signal_key == f"{sig.drug}||{sig.symptom}",
                SignalSnapshot.week_start == week,
                SignalSnapshot.project_id == (project_id if project_id is not None else sig.project_id),
            )
            .first()
        )
        payload = dict(
            signal_id=sig.id,
            project_id=project_id if project_id is not None else sig.project_id,
            signal_key=f"{sig.drug}||{sig.symptom}",
            drug=sig.drug,
            symptom=sig.symptom,
            week_start=week,
            post_count=sig.post_count or 0,
            prr=sig.prr,
            ic025=sig.ic025,
            eb05=sig.eb05,
            ror=sig.ror,
            strength=sig.strength,
            sdr_flag=bool(sig.sdr_flag),
            label_novelty=sig.label_novelty,
            captured_at=datetime.utcnow(),
        )
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
        else:
            db.add(SignalSnapshot(**payload))
        n += 1
    if n:
        db.commit()
    return n


def _trajectory(prev: Optional[SignalSnapshot], cur: Optional[SignalSnapshot]) -> str:
    if cur is None:
        return "unknown"
    if prev is None:
        return "new"
    # Prefer EB05 then IC025 then PRR for direction
    def _score(s: SignalSnapshot) -> float:
        if s.eb05 is not None:
            return float(s.eb05)
        if s.ic025 is not None:
            return float(s.ic025)
        return float(s.prr or 0)

    a, b = _score(prev), _score(cur)
    cnt_up = (cur.post_count or 0) > (prev.post_count or 0)
    if b > a * 1.15 or (b > a and cnt_up):
        return "strengthening"
    if b < a * 0.85:
        return "weakening"
    return "stable"


def _label_change_heuristic(snaps: List[SignalSnapshot], current: Signal) -> dict:
    """Non-regulatory heuristic for educational dashboards only."""
    score = 0.0
    reasons = []
    if current.sdr_flag:
        score += 0.25
        reasons.append("current SDR")
    if (current.label_novelty or "") == "novel":
        score += 0.30
        reasons.append("labeling gap (novel)")
    if len(snaps) >= 2 and _trajectory(snaps[-2], snaps[-1]) == "strengthening":
        score += 0.25
        reasons.append("strengthening trajectory")
    if (current.post_count or 0) >= 5:
        score += 0.10
        reasons.append("case volume ≥5")
    if (current.eb05 or 0) >= 2:
        score += 0.10
        reasons.append("EB05≥2")
    score = min(0.95, round(score, 2))
    band = "higher" if score >= 0.6 else "moderate" if score >= 0.35 else "lower"
    return {
        "likelihood_band": band,
        "score": score,
        "reasons": reasons,
        "disclaimer": (
            "Heuristic only — not a prediction of FDA/EMA label action. "
            "Prototype; not for regulatory decision-making."
        ),
    }


def get_casefile(
    db: Session,
    sig: Signal,
    *,
    limit: int = 26,
) -> dict:
    """Return longitudinal casefile for a signal."""
    key = f"{sig.drug}||{sig.symptom}"
    q = (
        db.query(SignalSnapshot)
        .filter(SignalSnapshot.signal_key == key)
        .order_by(SignalSnapshot.week_start.asc())
    )
    if sig.project_id is not None:
        q = q.filter(SignalSnapshot.project_id == sig.project_id)
    snaps = q.all()
    # Ensure current week is represented even before next scheduled snapshot
    if not snaps or snaps[-1].week_start < _week_start():
        # ephemeral current point (not persisted here)
        pass

    timeline = [
        {
            "week_start": s.week_start.isoformat() if s.week_start else None,
            "post_count": s.post_count,
            "prr": s.prr,
            "ic025": s.ic025,
            "eb05": s.eb05,
            "ror": s.ror,
            "strength": s.strength,
            "sdr_flag": bool(s.sdr_flag),
            "label_novelty": s.label_novelty,
        }
        for s in snaps[-limit:]
    ]

    prev = snaps[-2] if len(snaps) >= 2 else None
    cur = snaps[-1] if snaps else None
    traj = _trajectory(prev, cur)
    # If no history yet, treat as new this week from live signal
    if not snaps:
        traj = "new"
        timeline = [{
            "week_start": _week_start().isoformat(),
            "post_count": sig.post_count,
            "prr": sig.prr,
            "ic025": sig.ic025,
            "eb05": sig.eb05,
            "ror": sig.ror,
            "strength": sig.strength,
            "sdr_flag": bool(sig.sdr_flag),
            "label_novelty": sig.label_novelty,
            "live": True,
        }]

    return {
        "signal_id": sig.id,
        "drug": sig.drug,
        "event": sig.meddra_pt or sig.symptom,
        "trajectory": traj,
        "timeline": timeline,
        "n_snapshots": len(snaps),
        "label_change_heuristic": _label_change_heuristic(snaps, sig),
        "note": (
            "Weekly DMA memory for continuous surveillance. "
            "Compare latest vs prior week for strengthening / weakening."
        ),
    }
