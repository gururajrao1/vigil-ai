"""Stage 3 — NER context identification (Comprehend Medical–style).

Async-friendly handler that extracts clinical entities and assigns a stable
Concept Unique Identifier (CUI) in RxNorm / ICD-10-CM–inspired namespaces.
Offline-first: lexicon + vernacular + optional transformer NER; never requires
a cloud API key.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any, Dict, List, Optional

from .stage1_sanitize import fold_key, sanitize_surface
from .stage2_synonyms import resolve_synonym

_ICD10_SURROGATE: dict[str, str] = {
    "HEADACHE": "R51",
    "MIGRAINE": "G43.9",
    "NAUSEA": "R11.0",
    "VOMITING": "R11.10",
    "DIARRHOEA": "R19.7",
    "DIARRHEA": "R19.7",
    "RASH": "R21",
    "DYSPNOEA": "R06.0",
    "DYSPNEA": "R06.0",
    "CHESTPAIN": "R07.9",
    "ANAPHYLACTICREACTION": "T78.2",
    "HYPERSENSITIVITY": "T78.40",
    "PARAESTHESIA": "R20.2",
    "PARESTHESIA": "R20.2",
    "SEIZURE": "R56.9",
    "PYREXIA": "R50.9",
    "FATIGUE": "R53.83",
    "ANXIETY": "F41.9",
    "DEPRESSION": "F32.9",
    "SUICIDALIDEATION": "R45.851",
    "MYOCARDITIS": "I40.9",
    "PALPITATIONS": "R00.2",
}


def assign_cui(*, kind: str, surface: str, normalized: str = "",
               rxcui: Optional[str] = None, pt: Optional[str] = None) -> str:
    """Stable CUI in RxNorm / ICD-10-CM / VigilAI surrogate namespaces."""
    if kind in ("drug", "product") and rxcui:
        return f"RXNORM:{rxcui}"
    fold = fold_key(normalized or surface)
    if kind in ("drug", "product", "device"):
        if fold:
            digest = hashlib.sha1(fold.encode("utf-8")).hexdigest()[:10]
            return f"RXNORM:VIG-{digest}"
        return "RXNORM:UNKNOWN"
    # Events / symptoms → ICD-10-CM surrogate when known, else MedDRA-style PT CUI
    label = fold_key(pt or normalized or surface)
    if label in _ICD10_SURROGATE:
        return f"ICD10CM:{_ICD10_SURROGATE[label]}"
    if label:
        digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:10]
        return f"MEDDRA_SUR:{digest}"
    return "MEDDRA_SUR:UNKNOWN"


def _attach_cuis(entities: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {"drugs": [], "symptoms": [], "conditions": []}
    for d in entities.get("drugs", []):
        row = dict(d)
        syn = resolve_synonym(row.get("normalized") or row.get("text") or "", kind="product")
        if syn:
            row["normalized"] = syn
            row["generic"] = syn
        row["cui"] = assign_cui(
            kind="device" if row.get("product_type") == "device" else "drug",
            surface=row.get("text") or "",
            normalized=row.get("normalized") or "",
            rxcui=row.get("rxcui"),
        )
        out["drugs"].append(row)
    for s in entities.get("symptoms", []):
        row = dict(s)
        row["cui"] = assign_cui(
            kind="event",
            surface=row.get("text") or "",
            normalized=row.get("normalized") or "",
            pt=row.get("pt"),
        )
        out["symptoms"].append(row)
    for c in entities.get("conditions", []):
        row = dict(c)
        row["cui"] = assign_cui(
            kind="event",
            surface=row.get("text") or "",
            normalized=row.get("normalized") or "",
        )
        out["conditions"].append(row)
    return out


def extract_entities_with_cui(text: str, use_transformer: bool | None = None) -> Dict[str, List[dict]]:
    """Synchronous NER + CUI assignment (Stage 3 core)."""
    from .entities import extract_entities

    cleaned = sanitize_surface(text).cleaned or text
    entities = extract_entities(cleaned, use_transformer=use_transformer)
    return _attach_cuis(entities)


async def extract_entities_with_cui_async(
    text: str, use_transformer: bool | None = None
) -> Dict[str, List[dict]]:
    """Async wrapper modeled on Comprehend Medical DetectEntitiesV2 layout."""
    return await asyncio.to_thread(extract_entities_with_cui, text, use_transformer)


def merge_by_cui(entities: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    """Collapse duplicate surfaces that share a CUI into one concept record."""
    merged: Dict[str, List[dict]] = {"drugs": [], "symptoms": [], "conditions": []}
    for bucket in ("drugs", "symptoms", "conditions"):
        by_cui: dict[str, dict] = {}
        for ent in entities.get(bucket, []):
            cui = ent.get("cui") or assign_cui(
                kind="drug" if bucket == "drugs" else "event",
                surface=ent.get("text") or "",
                normalized=ent.get("normalized") or "",
                rxcui=ent.get("rxcui"),
                pt=ent.get("pt"),
            )
            if cui not in by_cui:
                row = dict(ent)
                row["cui"] = cui
                row["aliases"] = [ent.get("text")] if ent.get("text") else []
                by_cui[cui] = row
            else:
                alias = ent.get("text")
                if alias and alias not in by_cui[cui].get("aliases", []):
                    by_cui[cui].setdefault("aliases", []).append(alias)
        merged[bucket] = list(by_cui.values())
    return merged
