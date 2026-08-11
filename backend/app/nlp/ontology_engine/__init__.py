"""Enterprise ontology mapping engine (offline-first, open surrogates).

One entry point — :func:`map_verbatim_to_full_ontology` — takes any verbatim span
produced by the 4-gate NLP layer and returns the normalized identity across the
terminology stack a PV/device-vigilance reviewer expects:

* events  → LLT → PT → HLT → HLGT → SOC (+ surrogate CUI / SNOMED / OAE)
* drugs   → ingredient → RxNorm-style id → ATC L1–L5 → ChEBI ID + SMILES
* devices → GMDN + EMDN + FDA/MDR risk class + SaMD flag + IMDRF failure mode

Everything resolves from curated offline artifacts; the optional keyless RxNorm /
ChEBI / ICD-11 enrichers only run when ``online=True`` is explicitly requested.
"""
from __future__ import annotations

from typing import List, Optional

from . import crosswalk, device_mapper, dictionary_store, drug_chemical_mapper, meddra_mapper
from .models import (
    ONTOLOGY_VERSION,
    SURROGATE_DISCLAIMER,
    AtcLevel,
    AuditStamp,
    ChemicalStructure,
    DeviceMap,
    DrugChemicalMap,
    FullOntologyMap,
    MeddraChain,
)

__all__ = [
    "map_verbatim_to_full_ontology",
    "engine_status",
    "ONTOLOGY_VERSION",
    "SURROGATE_DISCLAIMER",
    "AtcLevel",
    "AuditStamp",
    "ChemicalStructure",
    "DeviceMap",
    "DrugChemicalMap",
    "FullOntologyMap",
    "MeddraChain",
    "crosswalk",
    "device_mapper",
    "dictionary_store",
    "drug_chemical_mapper",
    "meddra_mapper",
]


def _detect_entity_type(verbatim: str) -> str:
    if device_mapper.is_known_device(verbatim):
        return "device"
    if drug_chemical_mapper.is_known_drug(verbatim):
        return "drug"
    return "event"


def map_verbatim_to_full_ontology(
    verbatim: str,
    entity_type: str = "auto",
    *,
    online: bool = False,
    failure_mode: str = "",
) -> FullOntologyMap:
    """Normalize one verbatim span across every terminology the engine covers."""
    term = (verbatim or "").strip()
    requested = entity_type if entity_type in {"auto", "event", "drug", "device"} else "auto"
    audit = AuditStamp(
        source="vigilai_ontology_engine",
        online_enrichment=online,
        dictionaries=dictionary_store.loaded_dictionaries(),
    )

    if not term:
        return FullOntologyMap(
            verbatim="",
            requested_entity_type=requested,
            resolved_entity_type="unresolved",
            notes=["Empty verbatim — nothing to map."],
            audit=audit,
        )

    resolved = requested if requested != "auto" else _detect_entity_type(term)
    notes: List[str] = []
    meddra: Optional[MeddraChain] = None
    drug: Optional[DrugChemicalMap] = None
    device: Optional[DeviceMap] = None

    if resolved == "device":
        device = device_mapper.map_device(term, failure_mode)
        if failure_mode:
            meddra = meddra_mapper.map_event(failure_mode, online=online)
            notes.append("Device failure modes are coded in IMDRF; the MedDRA chain "
                         "shown covers the patient-harm term, not the malfunction.")
        if not device.matched:
            notes.append("Device not in the GMDN/EMDN surrogate — verbatim retained.")
    elif resolved == "drug":
        drug = drug_chemical_mapper.map_drug(term, online=online)
        if not drug.matched:
            notes.append("Ingredient not in the offline drug lexicon — verbatim retained.")
        elif not (drug.chemical and drug.chemical.smiles):
            notes.append("No SMILES in the ChEBI demo subset for this ingredient; "
                         "structure similarity is unavailable.")
    else:
        meddra = meddra_mapper.map_event(term, online=online)
        if not meddra.matched:
            notes.append("Event not in the MedDRA surrogate — coded as unmatched so "
                         "reviewers can see the gap instead of a false PT.")

    if resolved == "event" and meddra and not meddra.matched:
        resolved_type = "unresolved"
    elif resolved == "drug" and drug and not drug.matched:
        resolved_type = "unresolved"
    elif resolved == "device" and device and not device.matched:
        resolved_type = "unresolved"
    else:
        resolved_type = resolved

    cui = (meddra.cui if meddra else None) or (drug.cui if drug else None) \
        or (device.cui if device else None)

    codes = {
        "cui": cui,
        "meddra_pt": meddra.pt if meddra else None,
        "meddra_pt_code": meddra.pt_code if meddra else None,
        "meddra_soc": meddra.soc if meddra else None,
        "snomed_ct": meddra.snomed_ct if meddra else None,
        "oae": meddra.oae if meddra else None,
        "rxnorm": drug.rxnorm_id if drug else None,
        "atc": drug.atc_code if drug else None,
        "chebi": drug.chemical.chebi_id if drug and drug.chemical else None,
        "gmdn": device.gmdn_code if device else None,
        "emdn": device.emdn_code if device else None,
        "imdrf": device.imdrf_code if device else None,
    }

    return FullOntologyMap(
        verbatim=term,
        requested_entity_type=requested,
        resolved_entity_type=resolved_type,
        cui=cui,
        meddra=meddra,
        drug=drug,
        device=device,
        codes=codes,
        notes=notes,
        audit=audit,
    )


def engine_status() -> dict:
    """Dictionary provenance + coverage counts for API/diagnostics surfaces."""
    return {
        **dictionary_store.status(),
        "known_preferred_terms": meddra_mapper.known_pt_count(),
        "cui_anchors": crosswalk.index_size(),
        "optional_enrichers": [
            "RxNorm REST (keyless, online=true only)",
            "ChEBI via EBI OLS4 (keyless, online=true only)",
            "WHO ICD-11 (credentialled, online=true only)",
            "RDKit ECFP4 fingerprints (used automatically when installed)",
        ],
    }
