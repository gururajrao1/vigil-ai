"""Pydantic contracts for proactive risk stratification / population segmentation.

These schemas document the feature matrix and API/MCP payloads. Persistence still
uses SQLAlchemy models; demographics/comorbidities are derived at analysis time
from AE corpus text + entities (offline-first).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgeBracket(str, Enum):
    PEDIATRIC = "PEDIATRIC"
    ADULT = "ADULT"
    GERIATRIC = "GERIATRIC"
    UNKNOWN = "UNKNOWN"


class SexCode(str, Enum):
    FEMALE = "F"
    MALE = "M"
    UNKNOWN = "U"


class ProductDomain(str, Enum):
    DRUG = "drug"
    DEVICE = "device"
    VACCINE = "vaccine"
    COMBINATION = "combination"


class RiskFeatureRow(BaseModel):
    """One training / scoring row — X features + optional response."""

    post_id: Optional[int] = None
    product: str = ""
    product_type: ProductDomain = ProductDomain.DRUG
    atc_or_gmdn: Optional[str] = None
    age_years: Optional[float] = None
    age_bracket: AgeBracket = AgeBracket.UNKNOWN
    sex: SexCode = SexCode.UNKNOWN
    region: Optional[str] = None
    comorbidities: list[str] = Field(default_factory=list)
    comorbidity_cuis: list[str] = Field(default_factory=list)
    concomitant_meds: list[str] = Field(default_factory=list)
    target_ae_pt: Optional[str] = None
    severity_score: float = Field(
        0.0,
        description="0–1 ordinal proxy for Grade 3+ MedDRA-style severity",
    )
    severe_ae: bool = False


class ContributingFactor(BaseModel):
    factor: str
    shap_value: float
    direction: str = Field(description="elevates | protects")
    note: Optional[str] = None


class HighRiskSegment(BaseModel):
    segment_id: str
    label: str
    product: str
    target_ae_pt: str
    product_domain: ProductDomain = ProductDomain.DRUG
    n_cases: int = 0
    predicted_risk_score: float = Field(ge=0.0, le=1.0)
    relative_risk_elevation: float = Field(
        description="Odds / rate ratio vs baseline cohort (e.g. 3.4 = 3.4×)"
    )
    top_contributing_factors: list[ContributingFactor] = Field(default_factory=list)
    actionable_insight: str = ""
    ontology_refs: dict[str, Any] = Field(default_factory=dict)


class RiskStratificationRequest(BaseModel):
    product_id: str = Field(description="Drug / device / vaccine name or code")
    target_ae_pt: str = Field(description="MedDRA-style Preferred Term or symptom")
    min_confidence: float = Field(0.80, ge=0.0, le=1.0)
    product_type: Optional[ProductDomain] = None


class RiskStratificationResponse(BaseModel):
    product_id: str
    target_ae_pt: str
    model: str
    n_training_rows: int = 0
    n_positive: int = 0
    baseline_risk: float = 0.0
    segments: list[HighRiskSegment] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    ontology_stack: list[str] = Field(default_factory=list)
    needs_demo_seed: bool = False
    verdict: str = ""
    disclaimer: str = ""
