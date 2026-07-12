"""Seed default surveillance workspaces and backfill legacy rows."""
from __future__ import annotations

import json
import logging
import threading

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Alert, Project, RawPost, Signal

logger = logging.getLogger("vigilai.projects.seed")

_DEFAULT_PROJECTS = [
    {
        "name": "General Pharmacovigilance",
        "slug": "general-pv",
        "description": "Default worldwide drug safety listening workspace.",
        "therapeutic_area": "general",
        "keywords": ["adverse reaction", "side effect", "drug safety", "pharmacovigilance"],
    },
    {
        "name": "Oncology Surveillance",
        "slug": "oncology",
        "description": "Targeted oncology patient communities and immunotherapy AEs.",
        "therapeutic_area": "oncology",
        "keywords": ["immunotherapy", "checkpoint inhibitor", "chemotherapy side effects", "oncology forum"],
    },
    {
        "name": "Vaccine Monitoring",
        "slug": "vaccine",
        "description": "Vaccine hesitancy, reactogenicity, and post-vaccination events.",
        "therapeutic_area": "vaccine",
        "keywords": ["vaccine side effects", "reactogenicity", "post vaccination", "immunization"],
    },
]


def ensure_projects(db: Session) -> Project:
    """Create default projects if missing; backfill NULL project_id on legacy rows."""
    default: Project | None = None
    for spec in _DEFAULT_PROJECTS:
        existing = db.query(Project).filter(Project.slug == spec["slug"]).first()
        if existing:
            if spec["slug"] == "general-pv":
                default = existing
            continue
        row = Project(
            name=spec["name"],
            slug=spec["slug"],
            description=spec["description"],
            therapeutic_area=spec["therapeutic_area"],
            keywords_json=json.dumps(spec["keywords"]),
            is_active=True,
        )
        db.add(row)
        db.flush()
        if spec["slug"] == "general-pv":
            default = row
        logger.info("Seeded project workspace: %s", spec["slug"])

    if default is None:
        default = db.query(Project).filter(Project.slug == "general-pv").first()

    if default:
        _backfill_project_ids(db, default.id)

    db.commit()

    # Fill empty workspaces in the background so /api/health stays fast on cold start.
    # Critical for Render free: ephemeral SQLite resets after sleep — without this,
    # non-tech demo users land on zeros everywhere.
    from ..config import settings

    if settings.auto_seed_demo:
        threading.Thread(target=_fill_empty_workspaces_async, daemon=True).start()
    return default  # type: ignore[return-value]


def _backfill_project_ids(db: Session, default_id: int) -> None:
    for model in (RawPost, Signal, Alert):
        updated = (
            db.query(model)
            .filter((model.project_id.is_(None)) | (model.project_id == 0))
            .update({model.project_id: default_id}, synchronize_session=False)
        )
        if updated:
            logger.info("Backfilled project_id=%s on %d %s rows", default_id, updated, model.__tablename__)


def project_stats(db: Session, project_id: int) -> dict:
    posts = db.query(func.count(RawPost.id)).filter(RawPost.project_id == project_id).scalar() or 0
    signals = db.query(func.count(Signal.id)).filter(Signal.project_id == project_id).scalar() or 0
    return {"post_count": int(posts), "signal_count": int(signals)}


def fill_project_workspace(db: Session, project: Project, days: int = 21) -> dict:
    """Ingest a therapeutic-area corpus into a project and recompute its signals."""
    from ..ingestion.synthetic import generate_area_corpus
    from ..pipeline import ingest_posts, recompute_signals

    area = (project.therapeutic_area or project.slug or "general").lower()
    posts = generate_area_corpus(area, days=days, seed=42 + (project.id or 0))
    for p in posts:
        p["project_id"] = project.id
        # Keep IDs unique per project so re-fills don't collide across workspaces.
        p["external_id"] = f"p{project.id}:{p.get('external_id', '')}"

    ingested = ingest_posts(
        db, posts,
        use_transformer=False,
        use_presidio=False,
        online_translation=False,
        project_id=project.id,
    )
    stats = recompute_signals(
        db, use_fda=False, with_narrative=False, project_id=project.id,
    )
    counts = project_stats(db, project.id)
    logger.info(
        "Filled project %s (%s): ingested=%s posts=%s signals=%s",
        project.slug, area, ingested, counts["post_count"], counts["signal_count"],
    )
    return {"ingested": ingested, "area": area, **counts, **stats}


def _fill_empty_workspaces_async() -> None:
    """Seed any empty default workspace so dashboards are never blank after cold start.

    Runs only when a workspace has zero posts (Neon/persistent DB → no-op after first fill).
    ``general-pv`` is filled first (default UI project) and polished with ``prepare_demo``.
    """
    from ..database import SessionLocal
    from ..demo import prepare_demo

    db = SessionLocal()
    try:
        # general-pv first so Overview/Signals/Alerts light up ASAP for visitors.
        for slug in ("general-pv", "oncology", "vaccine"):
            project = db.query(Project).filter(Project.slug == slug, Project.is_active.is_(True)).first()
            if not project:
                continue
            n = db.query(func.count(RawPost.id)).filter(RawPost.project_id == project.id).scalar() or 0
            if n > 0:
                continue
            logger.info("Auto-filling empty project workspace: %s", slug)
            fill_project_workspace(db, project)
            if slug == "general-pv":
                try:
                    prepare_demo(db)
                except Exception:
                    logger.exception("prepare_demo after general-pv auto-fill failed")
    except Exception:
        logger.exception("Workspace auto-fill failed")
    finally:
        db.close()
