"""UMLS-style concept index tying MedDRA / SNOMED / OAE / RxNorm / GMDN keys.

Curated anchors come from ``umls_cui_surrogate.json``. Everything else gets a
deterministic identifier minted from a SHA1 of ``kind:concept`` so the same term
always yields the same CUI across processes and restarts — the property that makes
a crosswalk usable for audit — without redistributing licensed UMLS content.
"""
from __future__ import annotations

import hashlib
from typing import Dict, Optional

from . import dictionary_store

_KIND_PREFIX = {"event": "event", "drug": "drug", "device": "device"}


def _digits(seed: str, width: int) -> str:
    return str(int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12], 16)).zfill(width)[:width]


def anchor_key(kind: str, concept: str) -> str:
    return f"{_KIND_PREFIX.get(kind, kind)}:{(concept or '').strip()}"


def mint_cui(kind: str, concept: str) -> str:
    """Deterministic surrogate CUI (never an NLM UMLS identifier)."""
    return "CUI-SUR-" + _digits(anchor_key(kind, concept), 7)


def mint_code(system: str, kind: str, concept: str, width: int = 8) -> str:
    """Deterministic surrogate code in the shape of ``system``."""
    return f"{system}:{_digits(f'{system}|{anchor_key(kind, concept)}', width)}"


def cui_for(kind: str, concept: str) -> str:
    if not (concept or "").strip():
        return ""
    anchors = dictionary_store.cui_anchors()
    row = anchors.get(anchor_key(kind, concept))
    if row and row.get("cui"):
        return str(row["cui"])
    return mint_cui(kind, concept)


def crosswalk_row(kind: str, concept: str) -> Dict[str, Optional[str]]:
    """All cross-system identifiers known (curated) or minted for one concept."""
    if not (concept or "").strip():
        return {}
    anchors = dictionary_store.cui_anchors()
    curated = dict(anchors.get(anchor_key(kind, concept)) or {})
    row: Dict[str, Optional[str]] = {
        "cui": curated.get("cui") or mint_cui(kind, concept),
        "is_curated_anchor": bool(curated),
    }
    if kind == "event":
        row["snomed_ct"] = curated.get("snomed") or mint_code("SNOMED_SUR", kind, concept, 9)
        row["oae"] = curated.get("oae") or mint_code("OAE_SUR", kind, concept, 7)
        row["meddra_pt_code"] = curated.get("meddra") or mint_code("MEDDRA_SUR:PT", kind, concept, 8)
    elif kind == "drug":
        row["rxnorm"] = curated.get("rxnorm") or f"RXNORM:VIG-{_digits(anchor_key(kind, concept), 6)}"
        row["atc"] = curated.get("atc")
    elif kind == "device":
        row["gmdn"] = curated.get("gmdn")
        row["emdn"] = curated.get("emdn")
    return row


def meddra_term_code(level: str, name: str) -> Optional[str]:
    """Surrogate MedDRA term code for any hierarchy tier."""
    if not (name or "").strip():
        return None
    return mint_code(f"MEDDRA_SUR:{level.upper()}", "event", name, 8)


def index_size() -> int:
    return len(dictionary_store.cui_anchors())
