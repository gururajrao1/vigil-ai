"""Alert resolution actions — connect the inbox to lifecycle + HCP review.

Acknowledge alone used to be a dead-end flag. These helpers make inbox buttons
drive the same workflow the Lifecycle board and Ops KPIs already use.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Alert, AuditLog, Signal
from .lifecycle import is_valid_transition


def resolve_alert(
    db: Session,
    alert_id: int,
    *,
    action: str = "seen",
    by: str = "analyst",
    notes: str = "",
) -> dict[str, Any]:
    """Acknowledge an alert and optionally advance the linked signal.

    Actions
    -------
    seen:
        Mark alert handled (seen). No signal change.
    investigate:
        Ack + move signal new→under_evaluation (if allowed) + review confirmed.
        Use when the analyst will dig into the pair.
    false_alarm:
        Ack + reject lifecycle (if allowed) + review dismissed.
        Use when the ping is noise / already known / not actionable.
    """
    a = db.get(Alert, alert_id)
    if not a:
        raise ValueError("alert not found")

    action = (action or "seen").lower().strip()
    if action not in {"seen", "investigate", "false_alarm"}:
        raise ValueError("action must be seen|investigate|false_alarm")

    a.acknowledged = True
    effects: dict[str, Any] = {
        "alert_id": alert_id,
        "acknowledged": True,
        "action": action,
        "signal_id": a.signal_id,
        "lifecycle_status": None,
        "review_state": None,
    }

    sig: Optional[Signal] = db.get(Signal, a.signal_id) if a.signal_id else None
    if sig and action == "investigate":
        current = sig.lifecycle_status or "new"
        if current == "new" and is_valid_transition(current, "under_evaluation"):
            sig.lifecycle_status = "under_evaluation"
            sig.lifecycle_owner = by
            sig.lifecycle_notes = notes or "Opened from Alerts inbox — investigating."
            sig.lifecycle_updated_at = datetime.utcnow()
            effects["lifecycle_status"] = "under_evaluation"
        elif current not in ("closed", "rejected"):
            # Already in workflow — keep status, still assign owner if empty
            if not sig.lifecycle_owner:
                sig.lifecycle_owner = by
            effects["lifecycle_status"] = current
        if (sig.review_state or "unreviewed") == "unreviewed":
            sig.review_state = "confirmed"
            sig.reviewed_by = by
            sig.reviewed_at = datetime.utcnow()
            effects["review_state"] = "confirmed"

    if sig and action == "false_alarm":
        current = sig.lifecycle_status or "new"
        if is_valid_transition(current, "rejected") or current not in ("closed", "rejected"):
            # Allow reject from any non-terminal state (same as board)
            if current not in ("closed", "rejected"):
                sig.lifecycle_status = "rejected"
                sig.lifecycle_owner = by
                sig.lifecycle_notes = notes or "Closed from Alerts inbox — false alarm / not actionable."
                sig.lifecycle_updated_at = datetime.utcnow()
                effects["lifecycle_status"] = "rejected"
        sig.review_state = "dismissed"
        sig.reviewed_by = by
        sig.reviewed_at = datetime.utcnow()
        effects["review_state"] = "dismissed"

    detail = {
        "action": action,
        "drug": a.drug,
        "symptom": a.symptom,
        "effects": effects,
        "notes": notes or None,
    }
    db.add(AuditLog(
        actor=by,
        action=f"alert_{action}",
        entity_type="alert",
        entity_id=alert_id,
        detail=json.dumps(detail),
    ))
    if sig and a.signal_id:
        db.add(AuditLog(
            actor=by,
            action=f"alert_{action}_signal",
            entity_type="signal",
            entity_id=a.signal_id,
            detail=json.dumps({
                "from_alert": alert_id,
                "lifecycle_status": effects.get("lifecycle_status"),
                "review_state": effects.get("review_state"),
            }),
        ))
    db.commit()
    return {"status": "ok", **effects}
