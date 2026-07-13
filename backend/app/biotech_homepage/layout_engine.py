"""Layout engine — local DB → editorial biotech homepage JSON."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..api.helpers import dashboard_stats, signal_to_dict
from ..models import Signal
from ..projects.scope import current_project_id
from .schema import (
    ActionNode,
    BiotechHomepageLayout,
    HeroManifesto,
    HeroStat,
    HonestyBlock,
    NavItem,
    NavigationNode,
    PipelineStage,
    SignalSpotlight,
    TechnologyPillar,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_scope(col, project_id: int | None):
    from sqlalchemy import or_

    if project_id is None:
        return True
    return or_(col == project_id, col.is_(None), col == 0)


def _pick_spotlight(
    db: Session,
    *,
    project_id: int | None,
    focus_drug: Optional[str],
) -> dict[str, Any] | None:
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(_project_scope(Signal.project_id, project_id))
    if focus_drug:
        q = q.filter(Signal.drug.ilike(f"%{focus_drug.strip()}%"))
    # Prefer STRONG with highest PRR; fall back to any ranked pair
    strong = (
        q.filter(Signal.strength == "STRONG")
        .order_by(Signal.prr.desc())
        .first()
    )
    if strong:
        return signal_to_dict(strong)
    row = q.order_by(Signal.prr.desc()).first()
    return signal_to_dict(row) if row else None


def _spotlight_from_signal(s: dict[str, Any] | None, focus_drug: Optional[str]) -> SignalSpotlight:
    if not s:
        return SignalSpotlight(
            eyebrow="Signal narrative · waiting on corpus",
            headline="Load a workspace corpus to illuminate the first anomaly story",
            narrative=(
                "When social-listening posts clear the 4-gate AE detector and "
                "disproportionality crosses STRONG / MODERATE thresholds, VigilAI "
                "frames the pair as an editorial spotlight — prose first, math as flags."
            ),
            drug="—",
            event="—",
            flags=[],
            provenance_note="Live unstructured pipeline · no pair in scope yet",
            focus_drug=focus_drug,
        )

    drug = s.get("drug") or "product"
    event = (s.get("meddra") or {}).get("pt") or s.get("symptom") or "event"
    prr = s.get("prr")
    eb05 = s.get("eb05")
    ror = s.get("ror")
    n = s.get("post_count") or 0
    strength = s.get("strength") or "—"

    flags = []
    if prr is not None:
        flags.append({"key": "PRR", "value": f"{float(prr):.2f}", "tone": "mint"})
    if eb05 is not None:
        flags.append({"key": "EB05", "value": f"{float(eb05):.2f}", "tone": "sky"})
    if ror is not None:
        flags.append({"key": "ROR", "value": f"{float(ror):.2f}", "tone": "mint"})
    flags.append({"key": "N", "value": str(n), "tone": "neutral"})
    flags.append({"key": "TIER", "value": strength, "tone": "sky"})

    patient = None
    # Soft patient-voice line — no PII; clinical narrative only
    if event and drug:
        patient = (
            f"Across patient-voice threads, {event.lower()} recurs in proximity to {drug} — "
            f"enough co-occurrence to surface as a {strength} disproportionality pair."
        )

    return SignalSpotlight(
        eyebrow="Signal narrative spotlight",
        headline=f"{drug.title()} → {event}",
        narrative=(
            f"In the current workspace, {drug} and {event} form a disproportionate "
            f"product–event pair under frequentist and Bayesian screens. "
            f"This card is an editorial frame — not a spreadsheet cell — so reviewers "
            f"read the clinical story before the arithmetic."
        ),
        patient_voice=patient,
        drug=drug,
        event=event,
        flags=flags,
        href=f"/signals/{s.get('id')}" if s.get("id") else "/signals",
        provenance_note=(
            "Stats from live unstructured pipeline DMA on workspace posts. "
            "Any FAERS/MAUDE comparison elsewhere uses local reference surrogates — "
            "not live VigiBase or Sentinel."
        ),
        focus_drug=focus_drug,
    )


def render_biotech_homepage(
    db: Session,
    focus_drug: Optional[str] = None,
    *,
    project_id: int | None = None,
) -> dict[str, Any]:
    """Build the wire-format editorial homepage schema.

    LLM spatial awareness = this document. Mutate via focus_drug or by extending
    nodes in this engine — React only paints.
    """
    pid = project_id if project_id is not None else current_project_id()
    stats = dashboard_stats(db, project_id=pid)
    spotlight_sig = _pick_spotlight(db, project_id=pid, focus_drug=focus_drug)

    posts = stats.get("total_posts") or 0
    ae = stats.get("ae_posts") or 0
    signals = stats.get("signal_count") or 0

    layout = BiotechHomepageLayout(
        generated_at=_now_iso(),
        focus_drug=focus_drug,
        meta={
            "project_id": pid,
            "spatial": {
                "nav": "top-editorial",
                "hero": "manifesto-cinematic",
                "pillars": "four-gate-blocks",
                "swimlane": "pipeline-horizontal",
                "spotlight": "prose-editorial",
            },
            "stitch_design_ref": {
                "theme": "life_sciences_obsidian_v1",
                "note": (
                    "Google Stitch MCP is design-time. Runtime canvas uses this JSON "
                    "via FastMCP render_biotech_homepage."
                ),
            },
        },
        navigation=NavigationNode(
            brand="VigilAI",
            wordmark_sub="Computational pharmacovigilance",
            env_tags=["OFFLINE-FIRST", "SURROGATE BENCHMARKS", "PROTOTYPE"],
            items=[
                NavItem(id="mission", label="Mission", href="/#manifesto"),
                NavItem(id="tech", label="Technology", href="/#pillars"),
                NavItem(id="signal", label="Spotlight", href="/#spotlight"),
                NavItem(id="platform", label="Login", href="/login", emphasis=True),
            ],
        ),
        hero_manifesto=HeroManifesto(
            eyebrow="Post-market safety · patient voice at computational scale",
            title="See the signal before the spreadsheet.",
            lede=(
                "VigilAI is a life-sciences listening engine — unstructured patient "
                "narratives become disproportionality stories with honest provenance."
            ),
            body=(
                "We fuse a 4-gate adverse-event detector, offline-first NLP, and "
                "Bayesian screens (PRR · EB05 · IC025) into an editorial workspace. "
                "Comparative registry math runs on local reference surrogates — never "
                "a fake live pipe into VigiBase or Sentinel."
            ),
            env_tags=["LIVE LOCAL STREAM", "OPENFDA SURROGATE CACHE", "NOT FOR CLINICAL USE"],
            throughput=[
                HeroStat(
                    label="Stream throughput",
                    value=str(posts),
                    unit="docs",
                    provenance="live_unstructured_pipeline",
                ),
                HeroStat(
                    label="AE-gated yield",
                    value=str(ae),
                    unit="posts",
                    provenance="live_unstructured_pipeline",
                ),
                HeroStat(
                    label="Active pairs",
                    value=str(signals),
                    unit="signals",
                    provenance="live_unstructured_pipeline",
                ),
            ],
            primary_cta={"label": "Login", "href": "/login"},
            secondary_cta=None,
        ),
        technology_pillars=[
            TechnologyPillar(
                id="gate1",
                gate="GATE 01",
                title="Product entity lock",
                narrative=(
                    "Normalize drugs and devices to generic / GMDN-style codes before "
                    "any AE claim is admitted — brand noise never opens the gate alone."
                ),
                accent="mint",
            ),
            TechnologyPillar(
                id="gate2",
                gate="GATE 02",
                title="Symptom · malfunction map",
                narrative=(
                    "Lay language collapses onto MedDRA-style Preferred Terms (open "
                    "surrogate coding) so patient slang and device failures share one ontology."
                ),
                accent="sky",
            ),
            TechnologyPillar(
                id="gate3",
                gate="GATE 03",
                title="Negative sentiment pressure",
                narrative=(
                    "Only negatively oriented narratives continue — praise and neutral "
                    "chatter never inflate the disproportionality table."
                ),
                accent="mint",
            ),
            TechnologyPillar(
                id="gate4",
                gate="GATE 04",
                title="Non-negated clinical claim",
                narrative=(
                    "Negation and speculation are stripped. Surviving text enters DMA with "
                    "full gate traces — explainable, offline-capable, key-optional."
                ),
                accent="sky",
            ),
        ],
        pipeline_swimlane=[
            PipelineStage(
                id="ingest",
                label="Ingest",
                detail="Social · RSS · forge streams",
                state="active" if posts else "idle",
            ),
            PipelineStage(
                id="sanitize",
                label="Sanitize",
                detail="PII scrub · locale fold",
                state="active" if posts else "ready",
            ),
            PipelineStage(
                id="gates",
                label="4-Gate AE",
                detail="Entity · symptom · sentiment · negation",
                state="active" if ae else "ready",
            ),
            PipelineStage(
                id="dma",
                label="DMA",
                detail="PRR · ROR · EB05 · IC025",
                state="active" if signals else "ready",
            ),
            PipelineStage(
                id="narrative",
                label="Narrative",
                detail="Spotlight · workflow · E2B demo",
                state="active" if spotlight_sig else "idle",
            ),
        ],
        signal_spotlight=_spotlight_from_signal(spotlight_sig, focus_drug),
        honesty=HonestyBlock(
            title="Data integrity · biotech honesty",
            live_pipeline=(
                "Unstructured patient content is ingested and scored inside your "
                "workspace (crawlers, RSS, Data Forge). Throughput numbers above "
                "reflect that live local pipeline."
            ),
            surrogate_benchmarks=(
                "Comparative historical lookups (FAERS / MAUDE style) use local "
                "reference surrogate copies. They are benchmarks — not direct live "
                "queries to closed global registries."
            ),
            never_claim=[
                "Live WHO VigiBase / VigiLyze pipe",
                "Live FDA Sentinel multi-center feed",
                "Licensed MedDRA subscription sync",
            ],
        ),
        cta_strip={
            "title": "From manifesto to workbench",
            "body": "Keep the editorial stage for storytelling. Enter the platform for detection, lenses, and evidence.",
            "buttons": [
                {"label": "Dashboard", "href": "/dashboard"},
                {"label": "Safety Signals", "href": "/signals"},
                {"label": "Analytic Lenses", "href": "/lenses"},
            ],
        },
        actions=[
            ActionNode(
                id="forge_tick",
                label="Forge simulation pulse",
                kind="forge_sim",
                payload={"n": 5},
            ),
            ActionNode(
                id="recompute",
                label="Recompute pairs",
                kind="recompute",
                payload={},
            ),
            ActionNode(
                id="webhook_launch",
                label="Launch webhook stub",
                kind="webhook",
                payload={
                    "url_env": "VIGILAI_LAUNCH_WEBHOOK_URL",
                    "event": "biotech_homepage.focus",
                    "focus_drug": focus_drug,
                },
            ),
        ],
        disclaimer=(
            "Prototype. Synthetic data may be fictional. openFDA = US FAERS/MAUDE only. "
            "MedDRA coding is an open surrogate. Comparative cells are local reference "
            "surrogates — never live VigiBase/Sentinel. E2B is a demo template. "
            "Not for clinical use."
        ),
    )
    return layout.to_wire()
