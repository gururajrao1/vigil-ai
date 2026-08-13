"""Pydantic v2 contracts for the enterprise ontology mapping engine.

Every payload carries the audit stamp regulators expect from a coding step: the
raw verbatim beside the codes, the dictionary version used, whether the value came
from an offline surrogate or a live keyless API, and the surrogate disclaimer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ONTOLOGY_VERSION = "2026.08-surrogate.1"

SURROGATE_DISCLAIMER = (
    "Open MedDRA / UMLS / SNOMED-CT / GMDN / EMDN coding cache — authored offline "
    "crosswalks, not a licensed terminology distribution."
)

EntityType = Literal["auto", "event", "drug", "device"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditStamp(BaseModel):
    """Provenance attached to every mapping so coding decisions stay traceable."""

    source: str = "vigilai_ontology_engine"
    ontology_version: str = ONTOLOGY_VERSION
    is_surrogate: bool = True
    online_enrichment: bool = False
    dictionaries: List[str] = Field(default_factory=list)
    mapped_at: str = Field(default_factory=_now)
    disclaimer: str = SURROGATE_DISCLAIMER


class MeddraChain(BaseModel):
    """Full 5-tier MedDRA-style chain for one event verbatim."""

    verbatim: str
    llt: Optional[str] = None
    llt_code: Optional[str] = None
    pt: Optional[str] = None
    pt_code: Optional[str] = None
    hlt: Optional[str] = None
    hlt_code: Optional[str] = None
    hlgt: Optional[str] = None
    hlgt_code: Optional[str] = None
    soc: Optional[str] = None
    soc_code: Optional[str] = None
    soc_term_code: Optional[str] = None
    cui: Optional[str] = None
    snomed_ct: Optional[str] = None
    oae: Optional[str] = None
    icd11: Optional[str] = None
    matched: bool = False
    match_method: str = "unmatched"
    confidence: float = 0.0
    audit: AuditStamp = Field(default_factory=AuditStamp)

    def tiers(self) -> List[Dict[str, Optional[str]]]:
        """Top-down tier list — the shape the hierarchy tree component renders."""
        return [
            {"level": "SOC", "name": self.soc, "code": self.soc_term_code},
            {"level": "HLGT", "name": self.hlgt, "code": self.hlgt_code},
            {"level": "HLT", "name": self.hlt, "code": self.hlt_code},
            {"level": "PT", "name": self.pt, "code": self.pt_code},
            {"level": "LLT", "name": self.llt, "code": self.llt_code},
        ]


class AtcLevel(BaseModel):
    """One rung of the WHO ATC ladder (L1 anatomical … L5 chemical substance)."""

    level: int
    code: str
    label: str
    level_name: str


class ChemicalStructure(BaseModel):
    chebi_id: Optional[str] = None
    smiles: Optional[str] = None
    formula: Optional[str] = None
    iupac_style_names: List[str] = Field(default_factory=list)
    is_macromolecule: bool = False
    source: str = "chebi_surrogate"


class SimilarDrug(BaseModel):
    generic: str
    tanimoto: float
    method: str
    chebi_id: Optional[str] = None


class DrugChemicalMap(BaseModel):
    """Brand/typo → ingredient → ATC ladder → chemical structure."""

    verbatim: str
    preferred_generic: Optional[str] = None
    concept_id: Optional[str] = None
    brands: List[str] = Field(default_factory=list)
    generics: List[str] = Field(default_factory=list)
    rxnorm_id: Optional[str] = None
    rxcui: Optional[str] = None
    atc_code: Optional[str] = None
    atc_levels: List[AtcLevel] = Field(default_factory=list)
    chemical: Optional[ChemicalStructure] = None
    similar_drugs: List[SimilarDrug] = Field(default_factory=list)
    cui: Optional[str] = None
    matched: bool = False
    match_method: str = "unmatched"
    audit: AuditStamp = Field(default_factory=AuditStamp)


class DeviceMap(BaseModel):
    """Trade name / FDA product code / malfunction → GMDN + EMDN + risk class."""

    verbatim: str
    canonical_device: Optional[str] = None
    gmdn_code: Optional[str] = None
    gmdn_term: Optional[str] = None
    fda_product_code: Optional[str] = None
    emdn_code: Optional[str] = None
    emdn_term: Optional[str] = None
    fda_class: Optional[str] = None
    eu_mdr_class: Optional[str] = None
    is_samd: bool = False
    implantable: bool = False
    imdrf_code: Optional[str] = None
    imdrf_term: Optional[str] = None
    cui: Optional[str] = None
    matched: bool = False
    match_method: str = "unmatched"
    audit: AuditStamp = Field(default_factory=AuditStamp)


class FullOntologyMap(BaseModel):
    """Facade payload: one verbatim, every terminology it resolves into."""

    verbatim: str
    requested_entity_type: EntityType = "auto"
    resolved_entity_type: Literal["event", "drug", "device", "unresolved"] = "unresolved"
    cui: Optional[str] = None
    meddra: Optional[MeddraChain] = None
    drug: Optional[DrugChemicalMap] = None
    device: Optional[DeviceMap] = None
    codes: Dict[str, Optional[str]] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)
    audit: AuditStamp = Field(default_factory=AuditStamp)
