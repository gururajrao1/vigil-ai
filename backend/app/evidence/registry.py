"""Worldwide surveillance-source registry (spec section 3).

Models the global pharmacovigilance / device-vigilance ecosystem. Sources are tagged
by how VigilAI uses them:

  * "connector"  -> a real, keyless API we query live (openFDA FAERS, MAUDE, drug
                    labels, RxNorm, WHO ICD-11 if creds).
  * "surrogate"  -> licensed or distributed-infrastructure networks that cannot be
                    ingested offline (WHO VigiBase/VigiLyze, FDA Sentinel, NESTcc,
                    specialty registries). We represent them for architecture fidelity
                    and provide VigiLyze-style exploration over OUR OWN signal data.

This keeps the "comprehensive surveillance source architecture" honest: real where we
can be, clearly-labeled surrogate where the data is not openly available.
"""
from __future__ import annotations

from ..config import settings

REGISTRY = [
    # ---- Passive / spontaneous reporting (US) ----
    {"id": "faers", "name": "FDA FAERS (drug adverse events)", "region": "US",
     "type": "connector", "modality": "spontaneous", "product": "drug",
     "endpoint": "openFDA /drug/event.json", "key_required": False, "status": "live"},
    {"id": "maude", "name": "FDA MAUDE (device experience)", "region": "US",
     "type": "connector", "modality": "spontaneous", "product": "device",
     "endpoint": "openFDA /device/event.json", "key_required": False, "status": "live"},
    {"id": "labels", "name": "FDA Drug Labels (adverse reactions)", "region": "US",
     "type": "connector", "modality": "reference", "product": "drug",
     "endpoint": "openFDA /drug/label.json", "key_required": False, "status": "live"},
    {"id": "dailymed", "name": "DailyMed (NLM Structured Product Labels)", "region": "US",
     "type": "connector", "modality": "reference", "product": "drug",
     "endpoint": "dailymed /services/v2/spls.json", "key_required": False, "status": "live"},
    {"id": "drug_recall", "name": "FDA Drug Recalls / Enforcement", "region": "US",
     "type": "connector", "modality": "recall", "product": "drug",
     "endpoint": "openFDA /drug/enforcement.json", "key_required": False, "status": "live"},
    {"id": "device_recall", "name": "FDA Device Recalls / Enforcement", "region": "US",
     "type": "connector", "modality": "recall", "product": "device",
     "endpoint": "openFDA /device/enforcement.json", "key_required": False, "status": "live"},
    {"id": "device_class", "name": "FDA Device Classification (product code / class)",
     "region": "US", "type": "connector", "modality": "terminology", "product": "device",
     "endpoint": "openFDA /device/classification.json", "key_required": False, "status": "live"},
    {"id": "pubmed", "name": "PubMed / NCBI E-utilities (literature)", "region": "Global",
     "type": "connector", "modality": "literature", "product": "both",
     "endpoint": "eutils esearch/esummary", "key_required": False, "status": "live"},
    {"id": "medwatch", "name": "FDA MedWatch", "region": "US", "type": "surrogate",
     "modality": "spontaneous", "product": "both",
     "note": "Public entry point feeding FAERS/MAUDE; represented via those connectors."},
    {"id": "ismp", "name": "Institute for Safe Medication Practices (ISMP)", "region": "US",
     "type": "surrogate", "modality": "reference", "product": "drug",
     "note": "Medication-error reference; no open bulk API."},
    {"id": "medmarx", "name": "USP-MEDMARX medication-error database", "region": "US",
     "type": "surrogate", "modality": "registry", "product": "drug",
     "note": "Subscription database; modeled, not ingested."},

    # ---- Terminology / normalization ----
    {"id": "rxnorm", "name": "RxNorm / RxNav (drug normalization + ATC)", "region": "Global",
     "type": "connector", "modality": "terminology", "product": "drug",
     "endpoint": settings.rxnorm_base_url, "key_required": False, "status": "live"},
    {"id": "icd11", "name": "WHO ICD-11", "region": "Global", "type": "connector",
     "modality": "terminology", "product": "both", "endpoint": settings.icd11_base_url,
     "key_required": True, "status": "live" if getattr(settings, "icd11_client_id", "") else "needs_key"},

    # ---- Global / international ecosystem (licensed) ----
    {"id": "who_pidm", "name": "WHO Programme for International Drug Monitoring", "region": "Global",
     "type": "surrogate", "modality": "spontaneous", "product": "drug",
     "note": "Coordinated by UMC; membership network."},
    {"id": "vigibase", "name": "WHO VigiBase (via Uppsala Monitoring Centre)", "region": "Global",
     "type": "surrogate", "modality": "spontaneous", "product": "both",
     "note": "Licensed global ICSR database; not openly ingestible. VigiLyze-style "
             "exploration is emulated over VigilAI's own signal store."},
    {"id": "vigilyze", "name": "UMC VigiLyze (analytical suite)", "region": "Global",
     "type": "surrogate", "modality": "analytics", "product": "both",
     "note": "Emulated: disproportionality + drill-down exploration over our signals."},

    # ---- Active surveillance / distributed networks ----
    {"id": "sentinel", "name": "FDA Sentinel Initiative", "region": "US", "type": "surrogate",
     "modality": "active", "product": "drug",
     "note": "Distributed Common Data Model network; infrastructure, not an open API."},
    {"id": "nestcc", "name": "NESTcc (device evaluation)", "region": "US", "type": "surrogate",
     "modality": "active", "product": "device",
     "note": "Coordinated real-world device evidence network."},
    {"id": "cem", "name": "Cohort Event Monitoring (CEM)", "region": "Global", "type": "surrogate",
     "modality": "active", "product": "both", "note": "Prospective cohort AE monitoring framework."},
    {"id": "fda_best", "name": "FDA BEST (Biologics Effectiveness & Safety)", "region": "US",
     "type": "surrogate", "modality": "active", "product": "drug",
     "note": "Active surveillance for biologics/vaccines over claims + EHR data; distributed infrastructure, no open API."},
    {"id": "cdc_vsd", "name": "CDC Vaccine Safety Datalink (VSD)", "region": "US",
     "type": "surrogate", "modality": "active", "product": "drug",
     "note": "Linked EHR vaccine-safety network across US integrated health systems; data not openly ingestible."},
    {"id": "cnodes", "name": "CNODES (Canadian Network for Observational Drug Effect Studies)",
     "region": "Canada", "type": "surrogate", "modality": "active", "product": "drug",
     "note": "Distributed multi-province drug-safety/effectiveness network; protocol-driven, no open API."},
    {"id": "caefiss", "name": "CAEFISS (Canadian AEFI Surveillance System)", "region": "Canada",
     "type": "surrogate", "modality": "spontaneous", "product": "drug",
     "note": "National adverse-events-following-immunization surveillance (PHAC); not openly ingestible."},
    {"id": "mhra_yellowcard", "name": "UK MHRA Yellow Card Scheme", "region": "UK",
     "type": "surrogate", "modality": "spontaneous", "product": "both",
     "note": "UK spontaneous reporting for drugs/devices/vaccines; interactive iDAP portal, no clean open API."},
    {"id": "aspren", "name": "Australia ASPREN (Sentinel Practices Research Network)",
     "region": "Australia", "type": "surrogate", "modality": "active", "product": "drug",
     "note": "GP sentinel surveillance network (incl. AusVaxSafety active vaccine-safety monitoring); no open API."},
    {"id": "midnet", "name": "Japan MID-NET (Medical Information Database Network)", "region": "Japan",
     "type": "surrogate", "modality": "active", "product": "drug",
     "note": "PMDA distributed hospital-database network for active drug-safety assessment; access-restricted."},
    {"id": "china_adr", "name": "China National ADR Monitoring / Sentinel Alliance", "region": "China",
     "type": "surrogate", "modality": "spontaneous", "product": "drug",
     "note": "NMPA national ADR system + hospital sentinel alliance (CHPS); not openly ingestible."},

    # ---- Specialty registries ----
    {"id": "napr", "name": "National Pregnancy Registry for Atypical Antipsychotics",
     "region": "US", "type": "surrogate", "modality": "registry", "product": "drug",
     "note": "Neuropsychiatric pregnancy-exposure registry (high-risk cohort)."},
    {"id": "cviper", "name": "C-VIPER COVID-19 International Drug Registry", "region": "Global",
     "type": "surrogate", "modality": "registry", "product": "drug",
     "note": "Pandemic pregnancy-exposure registry."},
    {"id": "implant_reg", "name": "International Joint / Implant Registries", "region": "Global",
     "type": "surrogate", "modality": "registry", "product": "device",
     "note": "Longitudinal device-outcome registries."},
]


def registry_summary() -> dict:
    connectors = [s for s in REGISTRY if s["type"] == "connector"]
    surrogates = [s for s in REGISTRY if s["type"] == "surrogate"]
    return {
        "sources": REGISTRY,
        "counts": {
            "total": len(REGISTRY),
            "live_connectors": len([s for s in connectors if s.get("status") == "live"]),
            "connectors": len(connectors),
            "surrogates": len(surrogates),
        },
        "note": "Connectors are queried live with no API key (except ICD-11). "
                "Surrogates model licensed/distributed networks that cannot be ingested "
                "offline; VigiBase/VigiLyze exploration is emulated over VigilAI's own data.",
    }
