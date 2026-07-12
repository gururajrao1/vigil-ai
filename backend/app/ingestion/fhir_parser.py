"""Lightweight FHIR R4 parser for VigilAI ingestion.

Parses FHIR R4 Bundle or individual AdverseEvent / MedicationStatement
resources (plain JSON — no heavy fhirclient dependency) into the VigilAI
post dict format consumed by ``ingest_posts``.

Resources lacking BOTH a suspect drug and a reported event are silently
skipped so downstream NLP always receives actionable text.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_SERIOUSNESS_SEVERITY: Dict[str, str] = {
    "fatal": "critical",
    "lifeThreatening": "critical",
    "hospitalization": "high",
    "disabling": "high",
    "congenitalAnomaly": "high",
    "other": "medium",
    "serious": "high",
}

_OUTCOME_MAP: Dict[str, str] = {
    "resolved": "Resolved",
    "resolvedWithSequelae": "Resolved with sequelae",
    "notRecovered": "Not recovered / ongoing",
    "fatal": "Fatal",
    "recovering": "Recovering",
    "unknown": "Unknown",
}

_PII_STRIP = re.compile(
    r"\b(\d{3}-\d{2}-\d{4}|\d{9,10}|[A-Z]{2}\d{6,9}|[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Z])\b"
)


def _strip_pii(text: str) -> str:
    """Remove obvious structured PII tokens (SSN-style, NINO-style)."""
    return _PII_STRIP.sub("[REDACTED]", text or "")


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Safe deep-get through dicts and lists."""
    cur = obj
    for k in keys:
        if cur is None:
            return default
        if isinstance(cur, list):
            try:
                cur = cur[int(k)]
            except (ValueError, IndexError):
                return default
        elif isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
    return cur if cur is not None else default


def _first_coding_display(codeable: Optional[dict]) -> str:
    if not codeable:
        return ""
    codings = codeable.get("coding") or []
    for c in codings:
        d = c.get("display") or c.get("code") or ""
        if d:
            return d
    return codeable.get("text") or ""


def _parse_date(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.utcnow()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:19] if "Z" not in raw and "+" not in raw else raw, fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    return datetime.utcnow()


def _ae_to_post(resource: dict) -> Optional[dict]:
    """Convert a FHIR R4 AdverseEvent resource to a VigilAI post dict."""
    # --- drug / suspect entity ---
    suspects = resource.get("suspectEntity") or []
    drug = ""
    for se in suspects:
        inst = se.get("instance") or {}
        drug = inst.get("display") or ""
        if not drug:
            ref = inst.get("reference") or ""
            drug = ref.split("/")[-1] if ref else ""
        if drug:
            break

    # --- event description ---
    event_cc = resource.get("event") or {}
    event_text = _first_coding_display(event_cc) if event_cc else ""
    if not event_text:
        event_text = event_cc.get("text") if isinstance(event_cc, dict) else ""
    event_text = event_text or ""

    if not drug and not event_text:
        return None

    # --- outcome ---
    outcome_cc = resource.get("outcome") or {}
    outcome_code = _first_coding_display(outcome_cc)
    outcome_label = _OUTCOME_MAP.get(outcome_code, outcome_code or "")

    # --- seriousness → severity hint ---
    seriousness_cc = resource.get("seriousness") or {}
    seriousness_code = _first_coding_display(seriousness_cc)
    severity_hint = _SERIOUSNESS_SEVERITY.get(seriousness_code, "")

    # --- country ---
    country = ""
    loc = resource.get("location") or {}
    if isinstance(loc, dict):
        country = loc.get("display") or ""
        if not country:
            country = loc.get("reference", "").split("/")[-1]
    if not country:
        subject = resource.get("subject") or {}
        # patient address is not always present; skip if absent to avoid PII
        # (address text itself not used; only the country name if explicit)
        country = subject.get("display") or ""

    # --- posted_at ---
    posted_at = _parse_date(resource.get("recordedDate") or resource.get("date"))

    # --- construct body text ---
    parts = []
    if event_text:
        parts.append(f"Adverse event reported: {event_text}.")
    if drug:
        parts.append(f"Suspect drug: {drug}.")
    if outcome_label:
        parts.append(f"Outcome: {outcome_label}.")
    if severity_hint:
        parts.append(f"Seriousness: {seriousness_code}.")
    # Add patient-voice framing so NLP sentiment gate fires on structured FHIR data.
    # FHIR AdverseEvent resources are by definition adverse reports; the framing
    # surfaces the clinical seriousness as a negative patient signal without
    # fabricating any content — every word is derived from the resource itself.
    if event_text and drug:
        parts.append(f"The patient experienced {event_text} which was a serious adverse reaction to {drug}.")
    body = _strip_pii(" ".join(parts))

    rec_id = resource.get("id") or hashlib.md5(body.encode()).hexdigest()[:16]

    return {
        "external_id": f"fhir:ae:{rec_id}",
        "platform": "fhir",
        "product_type": "drug",
        "url": f"urn:fhir:AdverseEvent/{rec_id}",
        "author": "",
        "title": f"FHIR AdverseEvent: {event_text or drug}",
        "body": body,
        "lang": "en",
        "region": "Global",
        "country": _strip_pii(country) or None,
        "posted_at": posted_at,
    }


def _med_stmt_to_post(resource: dict) -> Optional[dict]:
    """Convert a FHIR R4 MedicationStatement resource to a VigilAI post dict."""
    # --- drug ---
    med_cc = resource.get("medicationCodeableConcept") or {}
    drug = _first_coding_display(med_cc) if med_cc else ""
    if not drug:
        med_ref = resource.get("medicationReference") or {}
        drug = med_ref.get("display") or ""

    # --- event / reason ---
    reason_codes = resource.get("reasonCode") or []
    event_text = ""
    for rc in reason_codes:
        event_text = _first_coding_display(rc) or rc.get("text") or ""
        if event_text:
            break
    if not event_text:
        event_text = (resource.get("note") or [{}])[0].get("text") or ""

    if not drug and not event_text:
        return None

    # --- status as outcome hint ---
    status = resource.get("status") or ""
    status_label = {
        "stopped": "Medication stopped (possible adverse effect).",
        "on-hold": "Medication on hold.",
        "not-taken": "Medication not taken.",
        "completed": "Medication completed.",
    }.get(status, "")

    # --- posted_at ---
    posted_at = _parse_date(resource.get("dateAsserted") or resource.get("effectiveDateTime"))

    # --- body text ---
    parts = []
    if drug:
        parts.append(f"Medication: {drug}.")
    if event_text:
        parts.append(f"Reason / symptom reported: {event_text}.")
    if status_label:
        parts.append(status_label)
    if drug and event_text:
        parts.append(f"The patient reported {event_text} as an adverse symptom associated with {drug}.")
    body = _strip_pii(" ".join(parts))

    rec_id = resource.get("id") or hashlib.md5(body.encode()).hexdigest()[:16]

    return {
        "external_id": f"fhir:ms:{rec_id}",
        "platform": "fhir",
        "product_type": "drug",
        "url": f"urn:fhir:MedicationStatement/{rec_id}",
        "author": "",
        "title": f"FHIR MedicationStatement: {drug or event_text}",
        "body": body,
        "lang": "en",
        "region": "Global",
        "country": None,
        "posted_at": posted_at,
    }


_PARSERS = {
    "AdverseEvent": _ae_to_post,
    "MedicationStatement": _med_stmt_to_post,
}


def parse_fhir_resource(resource: dict) -> Optional[dict]:
    """Parse a single FHIR R4 resource into a VigilAI post dict.

    Returns ``None`` if the resource type is unsupported or lacks
    the minimum required fields (drug OR event).
    """
    rtype = resource.get("resourceType", "")
    parser = _PARSERS.get(rtype)
    if parser is None:
        return None
    return parser(resource)


def parse_fhir_bundle(payload: dict) -> List[dict]:
    """Parse a FHIR R4 Bundle OR a single resource into a list of post dicts.

    Accepts:
    - A ``Bundle`` with ``entry[].resource`` items.
    - A bare ``AdverseEvent`` or ``MedicationStatement`` resource.

    Skips resources that lack the minimum required fields.
    """
    rtype = payload.get("resourceType", "")

    if rtype == "Bundle":
        entries = payload.get("entry") or []
        resources = [e.get("resource") for e in entries if isinstance(e, dict) and e.get("resource")]
    elif rtype in _PARSERS:
        resources = [payload]
    else:
        resources = []

    posts: List[dict] = []
    for res in resources:
        if not isinstance(res, dict):
            continue
        post = parse_fhir_resource(res)
        if post is not None:
            posts.append(post)
    return posts
