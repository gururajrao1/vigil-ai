"""Outbound alert dispatcher — webhook when ALERT_WEBHOOK_URL is set.

Falls back to an in-memory + audit-log delivery record so demos can show
"notify ops" without SMTP/Slack credentials.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from ..config import settings

# Recent deliveries for Command Center / Alerts UI (process-local).
_DELIVERIES: List[Dict[str, Any]] = []


def recent_deliveries(limit: int = 20) -> List[Dict[str, Any]]:
    return list(_DELIVERIES[:limit])


def dispatch_alert(alert: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """POST alert payload to ALERT_WEBHOOK_URL or record a simulated delivery."""
    payload = {
        "source": "VigilAI",
        "event": "pv_alert",
        "alert": alert,
        "sent_at": datetime.utcnow().isoformat() + "Z",
    }
    url = settings.alert_webhook_url
    result: Dict[str, Any] = {
        "ok": True,
        "mode": "simulated",
        "url": url or None,
        "payload": payload,
    }

    if url and not dry_run:
        try:
            import httpx
            r = httpx.post(url, json=payload, timeout=8.0)
            result["mode"] = "webhook"
            result["status_code"] = r.status_code
            result["ok"] = 200 <= r.status_code < 300
            if not result["ok"]:
                result["error"] = r.text[:300]
        except Exception as exc:
            result["ok"] = False
            result["mode"] = "webhook"
            result["error"] = f"{type(exc).__name__}: {exc}"
    elif not url:
        result["note"] = (
            "ALERT_WEBHOOK_URL not set — delivery recorded as simulated. "
            "Set a Slack/Teams/incoming webhook URL to push live."
        )

    entry = {
        "id": len(_DELIVERIES) + 1,
        "at": payload["sent_at"],
        "ok": result["ok"],
        "mode": result["mode"],
        "alert_id": alert.get("id"),
        "message": alert.get("message"),
        "severity": alert.get("severity"),
        "error": result.get("error"),
    }
    _DELIVERIES.insert(0, entry)
    del _DELIVERIES[50:]
    return result
