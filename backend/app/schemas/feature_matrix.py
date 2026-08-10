"""Pydantic v2 schemas for the Feature Store / 4-gate / privacy APIs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FeatureMatrixRequest(BaseModel):
    product_id: Optional[str] = Field(None, description="Filter product (brand or generic)")
    target_ae_pt: Optional[str] = Field(None, description="Filter MedDRA-style PT / event")
    project_id: Optional[int] = None
    include_explainability: bool = False
    min_n: int = 1


class FeatureMatrixResponse(BaseModel):
    n_rows: int
    n_source_ae_posts: int
    feature_names: List[str]
    matrix: List[Dict[str, Any]]
    X: List[List[Any]]
    row_keys: List[Dict[str, Any]]
    explainability: Optional[Dict[str, Any]] = None
    method: str = "product_event_cohort_feature_store_v1"
    ontology_stack: List[str] = Field(default_factory=list)
    disclaimer: str = ""


class FourGateRequest(BaseModel):
    text: str
    use_transformer: bool = False
    discard_near_neutral: bool = True


class HygieneRequest(BaseModel):
    title: str = ""
    body: str = ""
    author: str = ""
    project_id: Optional[int] = None


class OmopSyncRequest(BaseModel):
    project_id: Optional[int] = None
    limit: int = 500
    ae_only: bool = True


class AdapterRunRequest(BaseModel):
    adapter: str = Field(
        ...,
        description="faers | maude | literature | reddit | clinical_notes",
    )
    limit: int = 20
    query: Optional[str] = None
    apply_hygiene: bool = True
    project_id: Optional[int] = None
    # clinical_notes
    texts: Optional[List[str]] = None
    # literature
    source: Optional[str] = "pubmed"
    # reddit
    mode: Optional[str] = "health"
