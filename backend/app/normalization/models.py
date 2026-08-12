"""Pydantic v2 contracts for Deep Medical Concept Normalization (MCN)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

MCN_VERSION = "2026.08-mcn.1"

MCN_DISCLAIMER = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditStamp(BaseModel):
    source: str = "vigilai_mcn"
    version: str = MCN_VERSION
    is_surrogate: bool = True
    encoder_backend: str = "ngram"
    faiss_enabled: bool = False
    dictionaries: List[str] = Field(default_factory=list)
    mapped_at: str = Field(default_factory=_now)
    disclaimer: str = MCN_DISCLAIMER


class EmbeddingTrace(BaseModel):
    """Debug trace for SapBERT (or offline n-gram) embedding of a span."""

    verbatim: str
    vector_dim: int = 64
    encoder_backend: str = "ngram"
    vector_preview: List[float] = Field(default_factory=list)
    l2_norm: float = 0.0


class CandidateHit(BaseModel):
    cui: str
    preferred: str
    meddra_pt: Optional[str] = None
    snomed_ct: Optional[str] = None
    matched_surface: str
    cosine: float = 0.0
    rank: int = 1


class ConceptLink(BaseModel):
    """UMLS CUI + MedNorm/BERGAMOT dual map to MedDRA PT and SNOMED-CT."""

    verbatim: str
    matched: bool = False
    cui: Optional[str] = None
    preferred: Optional[str] = None
    meddra_pt: Optional[str] = None
    snomed_ct: Optional[str] = None
    kind: Optional[str] = None
    match_method: str = "unmatched"
    cosine: float = 0.0
    embedding: Optional[EmbeddingTrace] = None
    top_k: List[CandidateHit] = Field(default_factory=list)


class MentionInput(BaseModel):
    verbatim: str
    patient_count: int = Field(default=1, ge=0)


class AggregatedCohort(BaseModel):
    """Synonymous clinical mentions collapsed onto one CUI with summed N."""

    cui: str
    preferred: str
    meddra_pt: Optional[str] = None
    snomed_ct: Optional[str] = None
    variants: List[str] = Field(default_factory=list)
    patient_count: int = 0
    mention_count: int = 0


class CohortAggregationResult(BaseModel):
    inputs: List[MentionInput] = Field(default_factory=list)
    cohorts: List[AggregatedCohort] = Field(default_factory=list)
    total_patients: int = 0
    unresolved: List[str] = Field(default_factory=list)


class GeoResolution(BaseModel):
    verbatim: str
    matched: bool = False
    canonical: Optional[str] = None
    country: Optional[str] = None
    admin1: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    geonames_id: Optional[str] = None
    match_method: str = "unmatched"
    alias_used: Optional[str] = None


class ClinicalGeoNormalization(BaseModel):
    """Structured payload for normalize_clinical_and_geo_entities / MCP."""

    raw_clinical_term: str
    raw_location: str = ""
    clinical: ConceptLink
    geography: GeoResolution
    audit: AuditStamp = Field(default_factory=AuditStamp)


class MappingTracePayload(BaseModel):
    """Full debug payload for ConceptMappingTrace UI."""

    clinical: ConceptLink
    pipeline_steps: List[Dict[str, str]] = Field(default_factory=list)
    audit: AuditStamp = Field(default_factory=AuditStamp)


class EvalMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    n_cases: int
    true_positives: int
    false_positives: int
    false_negatives: int
    scope: Literal["clinical", "geo", "joint"] = "clinical"
