"""Step 1 — project-scoped FastAPI dependencies and query helpers."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional, TypeVar

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Query as SAQuery, Session

from ..database import get_db
from ..models import Project

T = TypeVar("T")

# Request-scoped active project (set by middleware from X-Project-Id).
_request_project_id: ContextVar[Optional[int]] = ContextVar("vigilai_project_id", default=None)


def set_request_project_id(project_id: Optional[int]):
    """Bind the active project for this request; returns a reset token."""
    return _request_project_id.set(project_id)


def reset_request_project_id(token) -> None:
    _request_project_id.reset(token)


def current_project_id() -> Optional[int]:
    """Active project for this request (header), if any."""
    return _request_project_id.get()


def get_project_id(
    x_project_id: Optional[int] = Header(None, alias="X-Project-Id"),
    project_id: Optional[int] = Query(None, alias="project_id"),
) -> Optional[int]:
    """Resolve active project from header (preferred) or query param."""
    return x_project_id or project_id


def get_active_project(
    db: Session = Depends(get_db),
    pid: Optional[int] = Depends(get_project_id),
) -> Project:
    """Require a valid, active project container for scoped endpoints."""
    if pid is None:
        default = (
            db.query(Project)
            .filter(Project.is_active.is_(True))
            .order_by(Project.id.asc())
            .first()
        )
        if default is None:
            raise HTTPException(
                status_code=400,
                detail="No project workspace configured. Create a project first.",
            )
        return default

    project = db.query(Project).filter(Project.id == pid, Project.is_active.is_(True)).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {pid} not found or inactive")
    return project


def scope_query(q: SAQuery, model, project_id: int) -> SAQuery:
    """Bound an ORM query to a single project workspace."""
    if hasattr(model, "project_id"):
        return q.filter(model.project_id == project_id)
    return q


def project_keywords(project: Project) -> list[str]:
    import json

    if not project.keywords_json:
        return []
    try:
        data = json.loads(project.keywords_json)
        return [str(k).strip() for k in data if str(k).strip()]
    except (json.JSONDecodeError, TypeError):
        return []
