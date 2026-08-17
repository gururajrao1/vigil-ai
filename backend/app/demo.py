"""Demo-preparation helpers.

Two jobs, both used to make a *live* demo compelling without changing any real
analytics:

  1. ``prepare_demo`` — back-dates each signal's detection time and its alert(s)
     across the corpus window and pre-reviews a handful of signals, so the KPIs
     page (time-to-detection, actionable rate, false-positive ratio) and the SPC
     control chart show a real distribution instead of a single point. This only
     touches detection/alert *timestamps* and HCP *review state* — it never
     fabricates external evidence or alters disproportionality statistics.

  2. ``prewarm_signals`` — eagerly enriches the top-ranked signals with the
     external keyless connectors (DailyMed / PubMed / recalls / device class) so
     they are cached and open instantly on stage. It runs sequentially over a
     small set (never a bulk fan-out) to stay within NCBI/openFDA rate limits.

All operations are deterministic and clearly synthetic (demo data).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .models import Alert, AuditLog, Signal


def _rank_key(s: Signal):
    return (1 if s.sdr_flag else 0, s.eb05 or 0.0, s.prr or 0.0, s.post_count or 0)


def prepare_demo(db: Session) -> dict:
    """Spread detection/alert timestamps + pre-review a few signals for the demo.

    Deterministic: detection lag and review picks are derived from signal id so
    reseeding always yields the same story.
    """
    now = datetime.utcnow()
    signals = db.query(Signal).all()
    if not signals:
        return {"prepared": 0}

    ranked = sorted(signals, key=_rank_key, reverse=True)

    reviewed = 0
    for s in signals:
        # --- realistic time-to-detection: earliest supporting post + a lag ---
        earliest = s.earliest_post_at or (now - timedelta(days=14))
        lag_days = 1 + (s.id * 7 + 3) % 12          # 1..12 days, deterministic
        lag_hours = (s.id * 5) % 24
        detected = earliest + timedelta(days=lag_days, hours=lag_hours)
        if detected > now:
            detected = now - timedelta(hours=(s.id % 12))
        if detected < earliest:
            detected = earliest + timedelta(hours=2)
        s.detected_at = detected
        s.first_seen = detected

    # --- spread alert timestamps to match their signal's detection day ---
    sig_by_id = {s.id: s for s in signals}
    for a in db.query(Alert).all():
        sig = sig_by_id.get(a.signal_id)
        if sig and sig.detected_at:
            a.created_at = sig.detected_at

    # --- pre-review a handful so actionable-rate / FP-ratio are meaningful ---
    #   confirm the strongest SDR/critical signals, dismiss a couple of weak ones.
    confirm = [s for s in ranked if s.sdr_flag][:4]
    weak = [s for s in reversed(ranked) if not s.sdr_flag and s.strength == "WEAK"][:2]
    for s in confirm:
        s.review_state = "confirmed"
        s.reviewed_by = "analyst"
        s.reviewed_at = now
        db.add(AuditLog(actor="analyst", action="signal_reviewed", entity_type="signal",
                        entity_id=s.id,
                        detail=f"{s.drug} -> {s.meddra_pt or s.symptom} marked confirmed"))
        reviewed += 1
    for s in weak:
        s.review_state = "dismissed"
        s.reviewed_by = "analyst"
        s.reviewed_at = now
        db.add(AuditLog(actor="analyst", action="signal_reviewed", entity_type="signal",
                        entity_id=s.id,
                        detail=f"{s.drug} -> {s.meddra_pt or s.symptom} marked dismissed (low priority)"))
        reviewed += 1

    db.commit()
    return {
        "prepared": len(signals),
        "confirmed": len(confirm),
        "dismissed": len(weak),
        "reviewed": reviewed,
    }


def prewarm_signals(db: Session, limit: int = 12) -> dict:
    """Eagerly enrich the top ``limit`` signals with external evidence (cached).

    Sequential (not a bulk fan-out) so we never trip NCBI/openFDA rate limits.
    Safe to run in a background thread with its own Session. No-op offline.
    """
    from .config import settings
    if not settings.use_evidence_enrichment:
        return {"prewarmed": 0, "skipped": "enrichment disabled"}

    from sqlalchemy import case

    from .evidence.enrich import enrich_one

    ranked = (
        db.query(Signal)
        .order_by(
            case((Signal.sdr_flag.is_(True), 1), else_=0).desc(),
            Signal.eb05.desc(),
            Signal.prr.desc(),
            Signal.post_count.desc(),
        )
        .limit(max(1, min(int(limit or 12), 25)))
        .all()
    )

    warmed = 0
    for s in ranked:
        if s.literature_json not in (None, "", "{}"):
            continue  # already cached
        try:
            ev = enrich_one(s.product_type or "drug", s.drug, s.symptom)
            s.label_evidence_json = json.dumps(ev.get("label_evidence") or {})
            s.recall_json = json.dumps(ev.get("recall") or {})
            s.literature_json = json.dumps(ev.get("literature") or {})
            s.device_class_json = json.dumps(ev.get("device_classification") or {})
            db.commit()
            warmed += 1
        except Exception:
            db.rollback()
        time.sleep(0.3)  # be polite to public APIs
    return {"prewarmed": warmed, "considered": len(ranked)}
