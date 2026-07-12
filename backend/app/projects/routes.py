"""FastAPI routes for the 6-step agentic pipeline."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..models import MonitoredQuery, PathfinderRun, Project, SuggestedSource
from .capabilities import pipeline_capabilities
from .divergence import compute_divergence, list_project_pairs
from .pathfinder import run_pathfinder
from .rdf_graph import kg_filter_options, sparql_subgraph
from .scope import get_active_project, project_keywords, scope_query
from .seed import fill_project_workspace, project_stats
from .source_queue import approve_and_onboard, source_to_dict
from .story import build_story, list_story_candidates, story_pdf_bytes

logger = logging.getLogger("vigilai.projects.routes")

router = APIRouter(prefix="/api/projects", tags=["projects"])


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #
class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    slug: str = Field(..., min_length=2, max_length=64)
    description: str = ""
    therapeutic_area: str = "general"
    keywords: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    therapeutic_area: Optional[str] = None
    keywords: Optional[list[str]] = None
    is_active: Optional[bool] = None


class MonitoredQueryCreate(BaseModel):
    query_text: str
    source_hint: Optional[str] = None


class ApproveSourceBody(BaseModel):
    storage_profile: Optional[str] = None


def _project_dict(p: Project, db: Session | None = None) -> dict:
    out = {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "therapeutic_area": p.therapeutic_area,
        "keywords": project_keywords(p),
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
    if db is not None:
        out.update(project_stats(db, p.id))
    return out


# --------------------------------------------------------------------------- #
# Step 1 — Projects
# --------------------------------------------------------------------------- #
@router.get("/capabilities")
def get_capabilities() -> dict:
    """Expose offline-first degradation modes for UI and ops."""
    return pipeline_capabilities()


@router.get("")
def list_projects(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(Project).filter(Project.is_active.is_(True)).order_by(Project.id).all()
    return [_project_dict(p, db) for p in rows]


@router.post("")
def create_project(body: ProjectCreate, db: Session = Depends(get_db)) -> dict:
    if db.query(Project).filter(Project.slug == body.slug).first():
        raise HTTPException(status_code=409, detail="Slug already exists")
    row = Project(
        name=body.name,
        slug=body.slug,
        description=body.description,
        therapeutic_area=body.therapeutic_area,
        keywords_json=json.dumps(body.keywords),
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _project_dict(row, db)


@router.get("/active")
def get_active(project: Project = Depends(get_active_project), db: Session = Depends(get_db)) -> dict:
    return _project_dict(project, db)


@router.post("/{project_id}/seed")
def seed_project(project_id: int, days: int = 21, db: Session = Depends(get_db)) -> dict:
    """Fill a project workspace with a therapeutic-area synthetic corpus + signals."""
    row = db.query(Project).filter(Project.id == project_id, Project.is_active.is_(True)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    result = fill_project_workspace(db, row, days=days)
    return {"project": _project_dict(row, db), **result}


@router.patch("/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)) -> dict:
    row = db.query(Project).filter(Project.id == project_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    if body.therapeutic_area is not None:
        row.therapeutic_area = body.therapeutic_area
    if body.keywords is not None:
        row.keywords_json = json.dumps(body.keywords)
    if body.is_active is not None:
        row.is_active = body.is_active
    db.commit()
    db.refresh(row)
    return _project_dict(row)


@router.get("/{project_id}/queries")
def list_queries(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(MonitoredQuery)
        .filter(MonitoredQuery.project_id == project_id, MonitoredQuery.is_active.is_(True))
        .all()
    )
    return [{"id": r.id, "query_text": r.query_text, "source_hint": r.source_hint} for r in rows]


@router.post("/{project_id}/queries")
def add_query(project_id: int, body: MonitoredQueryCreate, db: Session = Depends(get_db)) -> dict:
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    row = MonitoredQuery(project_id=project_id, query_text=body.query_text, source_hint=body.source_hint)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "query_text": row.query_text, "source_hint": row.source_hint}


# --------------------------------------------------------------------------- #
# Step 2 — Pathfinder
# --------------------------------------------------------------------------- #
def _bg_pathfinder(project_id: int) -> None:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project:
            import asyncio
            asyncio.run(run_pathfinder(db, project))
    except Exception as exc:
        logger.exception("Pathfinder background task failed: %s", exc)
    finally:
        db.close()


@router.post("/{project_id}/pathfinder/run")
def trigger_pathfinder(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    project = db.query(Project).filter(Project.id == project_id, Project.is_active.is_(True)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    background_tasks.add_task(_bg_pathfinder, project_id)
    return {"status": "started", "project_id": project_id, "message": "Pathfinder discovery loop queued"}


@router.post("/{project_id}/pathfinder/run-sync")
async def trigger_pathfinder_sync(project_id: int, db: Session = Depends(get_db)) -> dict:
    """Synchronous pathfinder for demos (blocks until complete)."""
    project = db.query(Project).filter(Project.id == project_id, Project.is_active.is_(True)).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    run = await run_pathfinder(db, project)
    return {
        "run_id": run.id,
        "status": run.status,
        "provider": run.provider,
        "urls_discovered": run.urls_discovered,
    }


@router.get("/{project_id}/pathfinder/runs")
def list_pathfinder_runs(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(PathfinderRun)
        .filter(PathfinderRun.project_id == project_id)
        .order_by(PathfinderRun.started_at.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "provider": r.provider,
            "urls_discovered": r.urls_discovered,
            "query_used": r.query_used,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Step 3 — Suggested Source Queue
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/sources/suggested")
def list_suggested_sources(
    project_id: int,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(SuggestedSource).filter(SuggestedSource.project_id == project_id)
    if status:
        q = q.filter(SuggestedSource.approval_status == status)
    rows = q.order_by(SuggestedSource.created_at.desc()).limit(100).all()
    return [source_to_dict(s) for s in rows]


@router.post("/{project_id}/sources/{source_id}/approve")
def approve_source(
    project_id: int,
    source_id: int,
    body: ApproveSourceBody,
    db: Session = Depends(get_db),
) -> dict:
    source = (
        db.query(SuggestedSource)
        .filter(SuggestedSource.id == source_id, SuggestedSource.project_id == project_id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Suggested source not found")
    return approve_and_onboard(db, source, storage_profile=body.storage_profile)


@router.post("/{project_id}/sources/{source_id}/reject")
def reject_source(project_id: int, source_id: int, db: Session = Depends(get_db)) -> dict:
    source = (
        db.query(SuggestedSource)
        .filter(SuggestedSource.id == source_id, SuggestedSource.project_id == project_id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Suggested source not found")
    source.approval_status = "rejected"
    db.commit()
    return {"ok": True, "id": source_id}


# --------------------------------------------------------------------------- #
# Step 5 — FAERS Divergence + Story Stepper
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/divergence/pairs")
def divergence_pairs(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    return list_project_pairs(db, project_id)


@router.get("/{project_id}/divergence")
def divergence_analysis(
    project_id: int,
    drug: str = Query(...),
    symptom: str = Query(...),
    days: int = Query(90, ge=14, le=365),
    db: Session = Depends(get_db),
) -> dict:
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    return compute_divergence(db, project_id, drug, symptom, days=days)


@router.get("/{project_id}/story/candidates")
def story_candidates(project_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    return list_story_candidates(db, project_id)


@router.get("/{project_id}/story")
def project_story(
    project_id: int,
    event: str = Query(...),
    drugs: str = Query(..., description="Comma-separated drug pair, e.g. simvastatin,atorvastatin"),
    db: Session = Depends(get_db),
) -> dict:
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    drug_list = [d.strip() for d in drugs.split(",") if d.strip()]
    try:
        return build_story(db, event=event, drugs=drug_list, project_id=project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{project_id}/story/pdf")
def project_story_pdf(
    project_id: int,
    event: str = Query(...),
    drugs: str = Query(...),
    db: Session = Depends(get_db),
):
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    drug_list = [d.strip() for d in drugs.split(",") if d.strip()]
    try:
        payload = build_story(db, event=event, drugs=drug_list, project_id=project_id)
        pdf = story_pdf_bytes(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    fname = f"vigilai_story_{event[:40].replace(' ', '_')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# --------------------------------------------------------------------------- #
# Step 6 — Parameterized SPARQL graph + story
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/graph/filters")
def graph_filter_options(project_id: int, db: Session = Depends(get_db)) -> dict:
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    return kg_filter_options(db, project_id)


@router.get("/{project_id}/graph/sparql")
def sparql_graph(
    project_id: int,
    drug: str = Query("", alias="drug"),
    symptom: str = Query("", alias="symptom"),
    region_param: str = Query("", alias="region"),
    country: str = Query("", alias="country"),
    condition: str = Query("", alias="condition"),
    focus_node: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    if not db.query(Project).filter(Project.id == project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    return sparql_subgraph(
        db,
        project_id=project_id,
        drug_param=drug,
        symptom_param=symptom,
        region_param=region_param,
        country_param=country,
        condition_param=condition,
        focus_node=focus_node,
        with_story=True,
    )
