"""Editorial website-map schema for the VigilAI biotech homepage canvas.

schema_version: vigilai.biotech_homepage.v1

Nodes (stable keys):
  navigation · hero_manifesto · technology_pillars · pipeline_swimlane
  signal_spotlight · honesty · cta_strip · actions
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SchemaVersion = Literal["vigilai.biotech_homepage.v1"]
ProvenanceMode = Literal["live_unstructured_pipeline", "local_reference_surrogate", "synthetic_forge"]


class NavItem(BaseModel):
    id: str
    label: str
    href: str
    emphasis: bool = False


class NavigationNode(BaseModel):
    brand: str = "VigilAI"
    wordmark_sub: str = "Life Sciences · Computational Safety"
    items: list[NavItem] = Field(default_factory=list)
    env_tags: list[str] = Field(default_factory=list)


class HeroStat(BaseModel):
    label: str
    value: str
    unit: Optional[str] = None
    provenance: ProvenanceMode = "live_unstructured_pipeline"


class HeroManifesto(BaseModel):
    eyebrow: str
    title: str
    lede: str
    body: str
    env_tags: list[str] = Field(default_factory=list)
    throughput: list[HeroStat] = Field(default_factory=list)
    primary_cta: dict[str, str] = Field(default_factory=dict)
    secondary_cta: dict[str, str] = Field(default_factory=dict)


class TechnologyPillar(BaseModel):
    id: str
    gate: str
    title: str
    narrative: str
    accent: Literal["mint", "sky"] = "mint"


class PipelineStage(BaseModel):
    id: str
    label: str
    detail: str
    state: Literal["active", "ready", "idle"] = "ready"


class SignalSpotlight(BaseModel):
    """Prose editorial card — not a spreadsheet row."""

    eyebrow: str
    headline: str
    narrative: str
    patient_voice: Optional[str] = None
    drug: str
    event: str
    flags: list[dict[str, str]] = Field(default_factory=list)
    href: Optional[str] = None
    provenance_note: str
    focus_drug: Optional[str] = None


class HonestyBlock(BaseModel):
    title: str
    live_pipeline: str
    surrogate_benchmarks: str
    never_claim: list[str] = Field(default_factory=list)


class ActionNode(BaseModel):
    id: str
    label: str
    kind: Literal["navigate", "forge_sim", "webhook", "recompute"] = "navigate"
    payload: dict[str, Any] = Field(default_factory=dict)


class BiotechHomepageLayout(BaseModel):
    schema_version: SchemaVersion = "vigilai.biotech_homepage.v1"
    generated_at: str
    focus_drug: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
    navigation: NavigationNode
    hero_manifesto: HeroManifesto
    technology_pillars: list[TechnologyPillar]
    pipeline_swimlane: list[PipelineStage]
    signal_spotlight: SignalSpotlight
    honesty: HonestyBlock
    cta_strip: dict[str, Any] = Field(default_factory=dict)
    actions: list[ActionNode] = Field(default_factory=list)
    disclaimer: str

    def to_wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
