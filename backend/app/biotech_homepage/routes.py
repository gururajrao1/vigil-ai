"""HTTP bridge for the biotech homepage schema (browser cannot speak MCP stdio)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..projects.scope import current_project_id
from .layout_engine import render_biotech_homepage

router = APIRouter(prefix="/api/biotech", tags=["biotech-homepage"])


@router.get("/homepage")
def get_biotech_homepage(
    focus_drug: Optional[str] = Query(None, description="Optional product for signal spotlight"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return render_biotech_homepage(
        db,
        focus_drug,
        project_id=current_project_id(),
    )
