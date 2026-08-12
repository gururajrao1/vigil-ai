"""Pydantic v2 contracts for the Omni-Search / brand-to-chemical gateway."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

SEARCH_VERSION = "2026.08-search.1"

SEARCH_DISCLAIMER = (
    "Offline-first Omni-Search surrogates inspired by CADEC / SMM4H / PharmaCoNER / "
    "MicroMeSH / BEL / RxNorm / RxE / RxClass. Not licensed corpus redistribution or "
    "a validated UMLS/RxNorm distribution. Prototype — not for regulatory or clinical use."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditStamp(BaseModel):
    source: str = "vigilai_search_engine"
    version: str = SEARCH_VERSION
    is_surrogate: bool = True
    online_enrichment: bool = False
    dictionaries: List[str] = Field(default_factory=list)
    mapped_at: str = Field(default_factory=_now)
    disclaimer: str = SEARCH_DISCLAIMER


class ExtractedSpan(BaseModel):
    text: str
    start: int = 0
    end: int = 0
    kind: Literal["drug", "event", "device", "substance", "unknown"] = "unknown"
    confidence: float = 0.0
    source: str = "lexicon"
    normalized_hint: Optional[str] = None


class LinkedConcept(BaseModel):
    verbatim: str
    preferred: str
    cui: Optional[str] = None
    match_method: str = "unmatched"
    score: float = 0.0
    kind: Literal["drug", "event", "device", "unknown"] = "unknown"


class IngredientRef(BaseModel):
    generic: str
    rxcui: Optional[str] = None
    rela: str = "Has_Ingredient"
    atc: Optional[str] = None


class BrandChemicalResolution(BaseModel):
    """Structured payload for resolve_brand_to_chemical / MCP."""

    query_term: str
    brand_rxcui: Optional[str] = None
    brand_name: Optional[str] = None
    umls_cui: Optional[str] = None
    ingredient_rxcuis: List[str] = Field(default_factory=list)
    ingredients: List[IngredientRef] = Field(default_factory=list)
    atc_classes: List[str] = Field(default_factory=list)
    atc_detail: List[dict] = Field(default_factory=list)
    manufacturer_hints: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    regions: List[str] = Field(default_factory=list)
    subset_brands: List[str] = Field(default_factory=list)
    matched: bool = False
    match_method: str = "unmatched"
    audit: AuditStamp = Field(default_factory=AuditStamp)


class UniverseSubsetRow(BaseModel):
    product: str
    event: str
    scope: Literal["universe", "subset"]
    post_count: int = 0
    prr: Optional[float] = None
    ror: Optional[float] = None
    chi_square: Optional[float] = None
    eb05: Optional[float] = None
    ic025: Optional[float] = None
    strength: Optional[str] = None
    sdr_flag: bool = False


class UniverseSubsetReport(BaseModel):
    query_term: str
    universe_ingredients: List[str] = Field(default_factory=list)
    subset_brands: List[str] = Field(default_factory=list)
    universe_rows: List[UniverseSubsetRow] = Field(default_factory=list)
    subset_rows: List[UniverseSubsetRow] = Field(default_factory=list)
    comparative: List[dict] = Field(default_factory=list)
    totals: Dict[str, int] = Field(default_factory=dict)
    verdict: str = ""
    how_to_read: str = ""
    audit: AuditStamp = Field(default_factory=AuditStamp)


class OmniSearchResult(BaseModel):
    query: str
    extracted: List[ExtractedSpan] = Field(default_factory=list)
    linked: List[LinkedConcept] = Field(default_factory=list)
    resolution: Optional[BrandChemicalResolution] = None
    suggestions: List[dict] = Field(default_factory=list)
    universe_subset: Optional[UniverseSubsetReport] = None
    notes: List[str] = Field(default_factory=list)
    audit: AuditStamp = Field(default_factory=AuditStamp)
