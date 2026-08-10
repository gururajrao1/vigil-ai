"""Inspection-readiness & lead-time escalation analytics (GVP Module IX).

Tracks review lead-time against SLA clocks, flags INSPECTION_RISK_WARNING,
requires structured medical rationale on REFUTED/CLOSED, and emits a
tamper-evident Signal Justification Log (SJL) with SHA-256 action hashes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# GVP-aligned SLA clocks (teaching / inspection-readiness surrogate)
SLA_URGENT_DAYS = 14
SLA_ROUTINE_DAYS = 30

_TERMINAL_REQUIRE_JUSTIFICATION = {"rejected", "closed"}
_URGENT_STRENGTHS = {"STRONG"}
_DISCLAIMER = (
    "Prototype GVP Module IX inspection-readiness analytics. "
    "Lead-time SLAs are operational surrogates for demo/teaching; "
    "not a validated inspection submission artifact."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_dt(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
    return None


def _sha256_hex(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_urgent_signal(sig: Any) -> bool:
    strength = (getattr(sig, "strength", None) or "").upper()
    if strength in _URGENT_STRENGTHS:
        return True
    if bool(getattr(sig, "sdr_flag", False)):
        return True
    if bool(getattr(sig, "maxsprt_crossed", False)):
        return True
    sev = (getattr(sig, "severity", None) or "").lower()
    return sev in ("critical", "high", "life-threatening")


def review_lead_time_days(sig: Any, *, as_of: Optional[datetime] = None) -> Optional[float]:
    """Days from first detection to QPPV/lifecycle action (or as_of if still open)."""
    detected = (
        _as_dt(getattr(sig, "detected_at", None))
        or _as_dt(getattr(sig, "first_seen", None))
        or _as_dt(getattr(sig, "earliest_post_at", None))
    )
    if not detected:
        return None
    action = _as_dt(getattr(sig, "lifecycle_updated_at", None))
    status = (getattr(sig, "lifecycle_status", None) or "new").lower()
    if status in ("new", "under_evaluation") or action is None:
        end = as_of or _utc_now()
    else:
        end = action
    delta = (end - detected).total_seconds() / 86400.0
    return round(max(0.0, delta), 2)


def sla_threshold_days(sig: Any) -> int:
    return SLA_URGENT_DAYS if is_urgent_signal(sig) else SLA_ROUTINE_DAYS


def inspection_risk_for_signal(sig: Any, *, as_of: Optional[datetime] = None) -> dict:
    """Per-signal SLA evaluation + inspection warning badge."""
    lead = review_lead_time_days(sig, as_of=as_of)
    thresh = sla_threshold_days(sig)
    urgent = is_urgent_signal(sig)
    status = (getattr(sig, "lifecycle_status", None) or "new").lower()
    overdue = lead is not None and lead > thresh and status not in ("closed", "rejected")
    notes = (getattr(sig, "lifecycle_notes", None) or "").strip()
    provisional = "[PROVISIONAL_JUSTIFICATION]" in notes
    justification_ok = True
    if status in _TERMINAL_REQUIRE_JUSTIFICATION:
        justification_ok = len(notes) >= 40 and not provisional

    badge = None
    if overdue:
        badge = "INSPECTION_RISK_WARNING"
    elif status in _TERMINAL_REQUIRE_JUSTIFICATION and not justification_ok:
        badge = "JUSTIFICATION_INCOMPLETE"

    return {
        "signal_id": getattr(sig, "id", None),
        "drug": getattr(sig, "drug", None),
        "event": getattr(sig, "meddra_pt", None) or getattr(sig, "symptom", None),
        "lifecycle_status": status,
        "urgent": urgent,
        "review_lead_time_days": lead,
        "sla_threshold_days": thresh,
        "overdue": overdue,
        "badge": badge,
        "justification_required": status in _TERMINAL_REQUIRE_JUSTIFICATION,
        "justification_ok": justification_ok,
        "justification_min_chars": 40,
        "disclaimer": _DISCLAIMER,
    }


def require_justification(status: str, notes: Optional[str]) -> Optional[str]:
    """Return error message if terminal status lacks structured rationale."""
    st = (status or "").lower()
    if st not in _TERMINAL_REQUIRE_JUSTIFICATION:
        return None
    text = (notes or "").strip()
    if len(text) < 40:
        return (
            f"GVP inspection-readiness: status '{st}' requires a structured medical "
            f"rationale of at least 40 characters in notes (got {len(text)})."
        )
    return None


def build_sj_entry(
    *,
    signal_id: int,
    actor: str,
    action: str,
    from_status: str,
    to_status: str,
    rationale: str,
    prev_hash: str = "GENESIS",
    meta: Optional[dict] = None,
) -> dict:
    """Immutable UTC-timestamped SJL row with SHA-256 action hash."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "signal_id": signal_id,
        "actor": actor or "system",
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "rationale": rationale or "",
        "timestamp_utc": ts,
        "prev_hash": prev_hash,
        "meta": meta or {},
    }
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    action_hash = _sha256_hex(canonical)
    return {**body, "action_hash": action_hash, "canonical": canonical}


def append_sj_to_notes(existing: Optional[str], entry: dict) -> str:
    """Embed latest SJL hash trail into lifecycle_notes without wiping rationale."""
    base = (existing or "").strip()
    trail = f"[SJL {entry['timestamp_utc']} {entry['action_hash'][:16]}…]"
    if trail in base:
        return base
    return (base + "\n" + trail).strip() if base else trail


def inspection_portfolio(db: Any, *, limit: int = 200) -> dict:
    """Aggregate SLA compliance metrics for QPPV / inspection dashboards."""
    from ..models import Signal

    rows = db.query(Signal).order_by(Signal.id.desc()).limit(max(1, min(limit, 1000))).all()
    evaluated = [inspection_risk_for_signal(s) for s in rows]
    overdue = [e for e in evaluated if e.get("overdue")]
    incomplete = [e for e in evaluated if e.get("badge") == "JUSTIFICATION_INCOMPLETE"]
    open_n = sum(
        1
        for e in evaluated
        if e.get("lifecycle_status") not in ("closed", "rejected")
    )
    return {
        "n_signals": len(evaluated),
        "n_open": open_n,
        "n_overdue": len(overdue),
        "n_justification_incomplete": len(incomplete),
        "sla_urgent_days": SLA_URGENT_DAYS,
        "sla_routine_days": SLA_ROUTINE_DAYS,
        "compliance_rate": round(
            1.0 - (len(overdue) / max(1, open_n)), 3
        ) if open_n else 1.0,
        "overdue": overdue[:40],
        "justification_gaps": incomplete[:40],
        "disclaimer": _DISCLAIMER,
    }


def build_signal_justification_log(db: Any, signal_id: int) -> dict:
    """Tamper-evident SJL export for one signal (hash-chained from AuditLog)."""
    from ..models import AuditLog, Signal

    sig = db.get(Signal, signal_id)
    if not sig:
        return {"error": "signal not found", "signal_id": signal_id}

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "signal", AuditLog.entity_id == signal_id)
        .order_by(AuditLog.id.asc())
        .all()
    )
    chain: list[dict] = []
    prev = "GENESIS"
    for row in logs:
        entry = build_sj_entry(
            signal_id=signal_id,
            actor=row.actor or "system",
            action=row.action or "audit",
            from_status="",
            to_status="",
            rationale=row.detail or "",
            prev_hash=prev,
            meta={"audit_log_id": row.id, "created_at": str(getattr(row, "created_at", ""))},
        )
        chain.append({k: entry[k] for k in entry if k != "canonical"})
        prev = entry["action_hash"]

    risk = inspection_risk_for_signal(sig)
    return {
        "signal_id": signal_id,
        "product": sig.drug,
        "event": sig.meddra_pt or sig.symptom,
        "lifecycle_status": sig.lifecycle_status,
        "lifecycle_notes": sig.lifecycle_notes,
        "inspection_risk": risk,
        "entries": chain,
        "chain_tip": prev,
        "n_entries": len(chain),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disclaimer": _DISCLAIMER,
    }


def render_sjl_markdown(payload: dict) -> str:
    lines = [
        f"# Signal Justification Log — #{payload.get('signal_id')}",
        "",
        f"**Product:** {payload.get('product')} → **Event:** {payload.get('event')}",
        f"**Lifecycle:** {payload.get('lifecycle_status')}",
        f"**Chain tip (SHA-256):** `{payload.get('chain_tip')}`",
        f"**Generated (UTC):** {payload.get('generated_at_utc')}",
        "",
        "## Inspection risk",
        f"- Lead time: {((payload.get('inspection_risk') or {}).get('review_lead_time_days'))} days",
        f"- SLA: {((payload.get('inspection_risk') or {}).get('sla_threshold_days'))} days",
        f"- Badge: {((payload.get('inspection_risk') or {}).get('badge')) or 'none'}",
        "",
        "## Action chain",
    ]
    for i, e in enumerate(payload.get("entries") or [], 1):
        lines.append(
            f"{i}. `{e.get('timestamp_utc')}` · {e.get('actor')} · {e.get('action')} · "
            f"hash `{e.get('action_hash', '')[:20]}…`"
        )
        if e.get("rationale"):
            lines.append(f"   - {e['rationale'][:400]}")
    lines.extend(["", f"_{payload.get('disclaimer')}_", ""])
    return "\n".join(lines)
