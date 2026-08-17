"""Pharmacovigilance operations KPIs + Statistical Process Control (SPC).

What a safety ops lead actually needs from this surface:
  1. How fast are we detecting? (latency — with caveats for synthetic corpora)
  2. What is the review backlog, and what should I review next?
  3. Of what we reviewed, how often do we confirm vs dismiss?
  4. Are alert volumes out of statistical control (Shewhart SPC)?
  5. Is documentation quality good enough to act (vigiGrade-style completeness)?

All derived from our own signal/alert/audit tables — deterministic and offline.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, load_only

from ..models import Alert, AuditLog, Signal


def _project_scope(col, project_id: Optional[int]):
    if project_id is None:
        return True
    return or_(col == project_id, col.is_(None), col == 0)


def _spc(daily_counts: List[int]) -> dict:
    """Shewhart control chart stats on a daily count series."""
    n = len(daily_counts)
    if n == 0:
        return {"mean": 0.0, "ucl": 0.0, "lcl": 0.0, "sigma": 0.0}
    mean = sum(daily_counts) / n
    var = sum((c - mean) ** 2 for c in daily_counts) / n
    sigma = var ** 0.5
    ucl = mean + 3 * sigma
    lcl = max(0.0, mean - 3 * sigma)
    return {
        "mean": round(mean, 2),
        "ucl": round(ucl, 2),
        "lcl": round(lcl, 2),
        "sigma": round(sigma, 2),
    }


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 2)


def compute_kpis(db: Session, project_id: Optional[int] = None) -> dict:
    """Ops KPIs via SQL aggregates — never load the full Signal ORM (JSON blobs)."""
    sig_base = db.query(Signal)
    if project_id is not None:
        sig_base = sig_base.filter(_project_scope(Signal.project_id, project_id))

    total = int(sig_base.with_entities(func.count(Signal.id)).scalar() or 0)

    def _count(*clauses) -> int:
        q = sig_base.with_entities(func.count(Signal.id))
        for c in clauses:
            q = q.filter(c)
        return int(q.scalar() or 0)

    confirmed = _count(Signal.review_state == "confirmed")
    dismissed = _count(Signal.review_state == "dismissed")
    reviewed = confirmed + dismissed
    unreviewed = max(0, total - reviewed)
    sdr = _count(Signal.sdr_flag.is_(True))
    strong = _count(Signal.strength == "STRONG")
    spike = _count(Signal.spike_flag.is_(True))
    well_documented = _count(Signal.well_documented.is_(True))

    mean_completeness = float(
        sig_base.with_entities(func.avg(Signal.completeness)).scalar() or 0.0
    )
    mean_completeness = round(mean_completeness, 3)

    actionable_rate = round(confirmed / reviewed, 3) if reviewed else None
    false_positive_ratio = round(dismissed / reviewed, 3) if reviewed else None
    backlog_rate = round(unreviewed / total, 3) if total else 0.0

    ttd_q = sig_base.with_entities(Signal.earliest_post_at, Signal.detected_at).filter(
        Signal.earliest_post_at.isnot(None),
        Signal.detected_at.isnot(None),
    )
    ttd_days: List[float] = []
    fresh_ttd: List[float] = []
    for earliest, detected in ttd_q.yield_per(1000):
        delta = (detected - earliest).total_seconds() / 86400.0
        if delta >= 0:
            ttd_days.append(round(delta, 2))
            if delta <= 30:
                fresh_ttd.append(round(delta, 2))
    ttd_sorted = sorted(ttd_days)
    fresh_sorted = sorted(fresh_ttd)

    triage_q = (
        sig_base.options(load_only(
            Signal.id, Signal.drug, Signal.symptom, Signal.meddra_pt,
            Signal.strength, Signal.severity, Signal.sdr_flag, Signal.spike_flag,
            Signal.prr, Signal.post_count, Signal.completeness, Signal.well_documented,
            Signal.review_state,
        ))
        .filter(
            or_(Signal.review_state == "unreviewed", Signal.review_state.is_(None)),
            or_(
                Signal.sdr_flag.is_(True),
                Signal.strength == "STRONG",
                Signal.spike_flag.is_(True),
            ),
        )
        .order_by(
            case((Signal.sdr_flag.is_(True), 0), else_=1),
            case((Signal.strength == "STRONG", 0), else_=1),
            case((Signal.spike_flag.is_(True), 0), else_=1),
            Signal.prr.desc(),
            Signal.post_count.desc(),
        )
        .limit(12)
    )
    triage_queue = [
        {
            "id": s.id,
            "drug": s.drug,
            "symptom": s.meddra_pt or s.symptom,
            "strength": s.strength,
            "severity": s.severity,
            "sdr_flag": bool(s.sdr_flag),
            "spike_flag": bool(s.spike_flag),
            "prr": round(s.prr or 0.0, 2),
            "post_count": s.post_count or 0,
            "completeness": round(s.completeness or 0.0, 2),
            "well_documented": bool(s.well_documented),
            "why": (
                "SDR (disproportionality meets Evans-style criteria)"
                if s.sdr_flag
                else "STRONG PRR/χ² tier"
                if s.strength == "STRONG"
                else "Spiking volume"
                if s.spike_flag
                else "Highest remaining PRR in backlog"
            ),
        }
        for s in triage_q.all()
    ]

    alert_q = db.query(Alert.created_at)
    if project_id is not None:
        alert_q = alert_q.filter(_project_scope(Alert.project_id, project_id))
    per_day: Dict[str, int] = defaultdict(int)
    alert_count = 0
    for (created,) in alert_q.yield_per(2000):
        alert_count += 1
        d = (created or datetime.utcnow()).date().isoformat()
        per_day[d] += 1
    dates = sorted(per_day.keys())
    counts = [per_day[d] for d in dates]
    spc = _spc(counts)
    spc_series = [
        {"date": d, "count": per_day[d], "breach": per_day[d] > spc["ucl"]}
        for d in dates
    ]
    breaches = [row for row in spc_series if row["breach"]]

    score = 0
    notes: List[str] = []
    if total == 0:
        notes.append("No signals yet — ingest sources or load the demo corpus.")
    else:
        if backlog_rate <= 0.2:
            score += 35
        elif backlog_rate <= 0.5:
            score += 22
            notes.append(f"{unreviewed} signals still unreviewed ({int(backlog_rate * 100)}% backlog).")
        elif backlog_rate < 1.0:
            score += 10
            notes.append(f"Heavy backlog: {unreviewed}/{total} unreviewed — start with the triage queue.")
        else:
            notes.append("100% unreviewed - confirm/dismiss from the triage queue to unlock actionable & FP rates.")

        if reviewed >= 10:
            score += 25
        elif reviewed >= 3:
            score += 15
            notes.append("Few HCP reviews yet - ratios stabilize after ~10 decisions.")
        elif reviewed > 0:
            score += 8
        else:
            notes.append("Actionable rate & false-positive ratio stay blank until signals are reviewed.")

        priority_n = _count(or_(Signal.sdr_flag.is_(True), Signal.strength == "STRONG"))
        if priority_n:
            pri_reviewed = _count(
                or_(Signal.sdr_flag.is_(True), Signal.strength == "STRONG"),
                Signal.review_state.in_(("confirmed", "dismissed")),
            )
            pri_rate = pri_reviewed / priority_n
            score += int(20 * pri_rate)
            if pri_rate < 0.5:
                notes.append(
                    f"Only {pri_reviewed}/{priority_n} SDR/STRONG signals reviewed - prioritize those first."
                )
        else:
            score += 10

        score += int(10 * (well_documented / total)) if total else 0

        if not breaches:
            score += 10
        elif len(breaches) <= 2:
            score += 5
            notes.append(f"{len(breaches)} alert-day(s) above UCL - check for emerging surges.")
        else:
            notes.append(f"{len(breaches)} out-of-control alert days - investigate volume spikes.")

    score = max(0, min(100, score))

    if ttd_days and (ttd_sorted[len(ttd_sorted) // 2] if ttd_sorted else 0) > 60:
        notes.append(
            "Mean time-to-detection is inflated by back-dated demo posts - use median / <=30d fresh window for live ops."
        )

    return {
        "project_id": project_id,
        "signal_count": total,
        "sdr_count": sdr,
        "strong_count": strong,
        "spike_count": spike,
        "alert_count": alert_count,
        "ops_score": score,
        "ops_status": (
            "healthy" if score >= 70 else "needs_attention" if score >= 40 else "blocked"
        ),
        "ops_notes": notes[:6],
        "time_to_detection_days": {
            "mean": round(sum(ttd_days) / len(ttd_days), 2) if ttd_days else 0.0,
            "median": _percentile(ttd_sorted, 0.5),
            "p90": _percentile(ttd_sorted, 0.9),
            "min": min(ttd_days) if ttd_days else 0.0,
            "max": max(ttd_days) if ttd_days else 0.0,
            "n": len(ttd_days),
            "fresh_mean": round(sum(fresh_ttd) / len(fresh_ttd), 2) if fresh_ttd else None,
            "fresh_median": _percentile(fresh_sorted, 0.5) if fresh_sorted else None,
            "fresh_n": len(fresh_ttd),
            "note": (
                "TTD = detected_at − earliest supporting post. "
                "Demo corpora with historical posted_at inflate the mean — prefer median / fresh (≤30d)."
            ),
        },
        "review": {
            "confirmed": confirmed,
            "dismissed": dismissed,
            "unreviewed": unreviewed,
            "reviewed": reviewed,
            "backlog_rate": backlog_rate,
            "actionable_rate": actionable_rate,
            "false_positive_ratio": false_positive_ratio,
            "note": (
                "Actionable = confirmed / reviewed. FP ratio = dismissed / reviewed. "
                "Both require HCP Confirm/Dismiss on Signal Detail (or triage below)."
            ),
        },
        "triage_queue": triage_queue,
        "triage_note": (
            "Queue lists unreviewed SDR / STRONG / spike only (read-time filter). "
            "WEAK signals remain in /api/signals and are not deleted or auto-dismissed."
        ),
        "spc": {
            **spc,
            "series": spc_series,
            "breach_count": len(breaches),
            "breaches": breaches[-8:],
            "interpretation": (
                "No days above UCL — alert volume in control."
                if not breaches
                else f"{len(breaches)} day(s) exceeded UCL (mean+3σ) — possible emerging surge."
            ),
        },
        "completeness": {
            "mean": mean_completeness,
            "well_documented": well_documented,
            "well_documented_rate": round(well_documented / total, 3) if total else 0.0,
            "note": "vigiGrade-style documentation-quality surrogate (0–1) from available case fields.",
        },
        "audit_trail_entries": db.query(AuditLog).count(),
        "glossary": {
            "ttd": "Days from first supporting patient post to when VigilAI first wrote the signal row.",
            "actionable_rate": "Share of HCP-reviewed signals marked confirmed (worth follow-up).",
            "false_positive_ratio": "Share of HCP-reviewed signals marked dismissed (noise / not actionable).",
            "sdr": "Signal of disproportionate reporting — PRR/ROR/χ² (or Bayesian) meet Evans-style thresholds.",
            "spc": "Shewhart control chart on daily alert counts; points above UCL are out-of-control.",
        },
    }


def recent_audit(db: Session, limit: int = 100) -> List[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
