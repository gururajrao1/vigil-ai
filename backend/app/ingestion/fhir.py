"""FHIR/HL7 ingestion — accept EHR-sourced safety data so VigilAI is hospital-integrable.

Parses a FHIR R4 Bundle (or a single resource / list) containing ``AdverseEvent`` and
``MedicationStatement`` (and optionally ``Patient``) resources into the internal
post-dict list that ``pipeline.ingest_posts`` consumes. Each adverse event becomes a
synthesized, clearly-labelled EHR record ("EHR-reported (FHIR): ...") so the existing
NLP/analytics pipeline extracts the suspect drug + reaction consistently and the case
flows through the same disproportionality / causality / evidence machinery as social
posts. Defensive about missing fields; entirely offline, no key.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List

# Minimal ISO country -> continent/region map (matches the corpus region vocabulary).
_COUNTRY_REGION = {
    "US": "North America", "USA": "North America", "United States": "North America",
    "CA": "North America", "Canada": "North America",
    "GB": "Europe", "UK": "Europe", "United Kingdom": "Europe",
    "DE": "Europe", "Germany": "Europe", "FR": "Europe", "France": "Europe",
    "IT": "Europe", "Italy": "Europe", "ES": "Europe", "Spain": "Europe",
    "IN": "Asia", "India": "Asia", "JP": "Asia", "Japan": "Asia",
    "CN": "Asia", "China": "Asia",
    "BR": "South America", "Brazil": "South America",
    "NG": "Africa", "Nigeria": "Africa",
    "AU": "Oceania", "Australia": "Oceania",
}
_COUNTRY_NAME = {
    "US": "United States", "USA": "United States", "CA": "Canada", "GB": "United Kingdom",
    "UK": "United Kingdom", "DE": "Germany", "FR": "France", "IT": "Italy",
    "IN": "India", "JP": "Japan", "CN": "China", "BR": "Brazil", "NG": "Nigeria",
    "AU": "Australia",
}


def _hash(s: str) -> str:
    return hashlib.sha1((s or "anon").encode()).hexdigest()[:12]


def _cc_text(cc: Any) -> str:
    """Extract a display string from a FHIR CodeableConcept (or plain str)."""
    if not cc:
        return ""
    if isinstance(cc, str):
        return cc.strip()
    if isinstance(cc, dict):
        if cc.get("text"):
            return str(cc["text"]).strip()
        for coding in cc.get("coding", []) or []:
            if isinstance(coding, dict) and coding.get("display"):
                return str(coding["display"]).strip()
    return ""


def _ref_id(ref: Any) -> str:
    """Return the bare id from a FHIR reference string like 'MedicationStatement/ms1' or '#med1'."""
    if isinstance(ref, dict):
        ref = ref.get("reference", "")
    if not isinstance(ref, str):
        return ""
    return ref.split("/")[-1].lstrip("#").strip()


def _iter_resources(payload: Any) -> List[dict]:
    """Yield FHIR resources from a Bundle, a single resource, or a list of resources."""
    if payload is None:
        return []
    if isinstance(payload, list):
        out: List[dict] = []
        for item in payload:
            out.extend(_iter_resources(item))
        return out
    if not isinstance(payload, dict):
        return []
    rtype = payload.get("resourceType")
    if rtype == "Bundle":
        res = []
        for entry in payload.get("entry", []) or []:
            r = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(r, dict):
                res.append(r)
        return res
    if rtype:
        return [payload]
    return []


def _patient_country(patient: dict) -> str | None:
    for addr in patient.get("address", []) or []:
        if isinstance(addr, dict) and addr.get("country"):
            return str(addr["country"]).strip()
    return None


def _med_drug(ms: dict) -> str:
    """Suspect drug from a MedicationStatement (R4: medicationCodeableConcept)."""
    drug = _cc_text(ms.get("medicationCodeableConcept"))
    if not drug and ms.get("medicationReference"):
        drug = _cc_text(ms["medicationReference"].get("display")
                        if isinstance(ms.get("medicationReference"), dict) else None)
    return drug


def parse_fhir_bundle(payload: Any) -> List[dict]:
    """Convert FHIR AdverseEvent/MedicationStatement resources into pipeline post-dicts."""
    resources = _iter_resources(payload)
    if not resources:
        return []

    meds_by_id: Dict[str, str] = {}
    meds_by_subject: Dict[str, str] = {}
    patients: Dict[str, dict] = {}
    adverse_events: List[dict] = []

    for r in resources:
        rtype = r.get("resourceType")
        if rtype == "MedicationStatement":
            drug = _med_drug(r)
            rid = r.get("id") or ""
            if rid:
                meds_by_id[rid] = drug
            subj = _ref_id(r.get("subject"))
            if subj and drug:
                meds_by_subject.setdefault(subj, drug)
        elif rtype == "Patient":
            if r.get("id"):
                patients[r["id"]] = r
        elif rtype == "AdverseEvent":
            adverse_events.append(r)

    posts: List[dict] = []
    for i, ae in enumerate(adverse_events):
        reaction = _cc_text(ae.get("event"))
        if not reaction:
            # R4B/R5 use .code; also try a nested reaction/manifestation
            reaction = _cc_text(ae.get("code"))
        # Resolve the suspect drug.
        drug = ""
        for se in ae.get("suspectEntity", []) or []:
            inst = se.get("instance") if isinstance(se, dict) else None
            if isinstance(inst, dict) and inst.get("display"):
                drug = str(inst["display"]).strip()
                break
            ref = _ref_id(inst)
            if ref and ref in meds_by_id:
                drug = meds_by_id[ref]
                break
        subj = _ref_id(ae.get("subject"))
        if not drug and subj in meds_by_subject:
            drug = meds_by_subject[subj]
        if not drug or not reaction:
            continue  # need both a suspect product and an event to form a signal

        # Timing.
        date_str = ae.get("date") or ae.get("recordedDate") or ""
        posted = datetime.utcnow()
        if date_str:
            try:
                posted = datetime.fromisoformat(str(date_str).replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                posted = datetime.utcnow()

        # Geography from the referenced patient, else the event's location.display.
        country_raw = None
        if subj in patients:
            country_raw = _patient_country(patients[subj])
        if not country_raw:
            loc = ae.get("location")
            if isinstance(loc, dict) and loc.get("display"):
                country_raw = str(loc["display"]).strip()
        region = _COUNTRY_REGION.get(country_raw or "", "Global")
        country = _COUNTRY_NAME.get(country_raw or "", country_raw)

        rid = ae.get("id") or f"ae{i}"
        body = (f"EHR-reported (FHIR): patient developed {reaction} after starting "
                f"{drug}. Recorded from the electronic health record.")
        posts.append({
            "external_id": f"fhir-{rid}",
            "platform": "ehr_fhir",
            "product_type": "drug",
            "url": "",
            "author": _hash(f"fhir-{subj or rid}"),
            "title": f"EHR adverse event: {drug}",
            "body": body,
            "lang": "en",
            "region": region,
            "country": country,
            "posted_at": posted,
        })
    return posts


def sample_bundle() -> dict:
    """A small, valid FHIR R4 Bundle for the demo (paste-and-ingest)."""
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "p1",
                          "address": [{"country": "US"}]}},
            {"resource": {"resourceType": "Patient", "id": "p2",
                          "address": [{"country": "IN"}]}},
            {"resource": {"resourceType": "Patient", "id": "p3",
                          "address": [{"country": "GB"}]}},
            {"resource": {"resourceType": "MedicationStatement", "id": "ms1",
                          "subject": {"reference": "Patient/p1"},
                          "medicationCodeableConcept": {"text": "warfarin"}}},
            {"resource": {"resourceType": "MedicationStatement", "id": "ms2",
                          "subject": {"reference": "Patient/p2"},
                          "medicationCodeableConcept": {"text": "metformin"}}},
            {"resource": {"resourceType": "MedicationStatement", "id": "ms3",
                          "subject": {"reference": "Patient/p3"},
                          "medicationCodeableConcept": {"text": "atorvastatin"}}},
            {"resource": {"resourceType": "AdverseEvent", "id": "ae1",
                          "subject": {"reference": "Patient/p1"},
                          "recordedDate": "2026-06-20",
                          "suspectEntity": [{"instance": {"reference": "MedicationStatement/ms1",
                                                          "display": "warfarin"}}],
                          "event": {"text": "haemorrhage"}}},
            {"resource": {"resourceType": "AdverseEvent", "id": "ae2",
                          "subject": {"reference": "Patient/p2"},
                          "recordedDate": "2026-06-24",
                          "suspectEntity": [{"instance": {"reference": "MedicationStatement/ms2"}}],
                          "event": {"text": "diarrhoea"}}},
            {"resource": {"resourceType": "AdverseEvent", "id": "ae3",
                          "subject": {"reference": "Patient/p3"},
                          "recordedDate": "2026-06-27",
                          "suspectEntity": [{"instance": {"reference": "MedicationStatement/ms3"}}],
                          "event": {"text": "muscle pain"}}},
        ],
    }
