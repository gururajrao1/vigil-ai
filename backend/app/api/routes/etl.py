"""ETL pipeline API — FAERS / SIDER / Athena-vocab sync into OMOP staging."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db, init_db
from ...etl_pipeline import SUPPORTED_DATASETS, trigger_dataset_sync
from ...nlp.validation import run_mcn_benchmark
from ...projects.scope import current_project_id

router = APIRouter(tags=["etl"])


@router.post("/etl/sync/{dataset_name}")
def etl_sync_dataset(
    dataset_name: str,
    limit: int = Query(200, ge=1, le=2000),
    force_fixture: bool = False,
    db: Session = Depends(get_db),
):
    """Trigger FAERS / SIDER / athena_vocab ingestion into OMOP staging."""
    init_db()
    return trigger_dataset_sync(
        dataset_name,
        db=db,
        project_id=current_project_id(),
        limit=limit,
        force_fixture=force_fixture,
    )


@router.get("/etl/sync/{dataset_name}")
def etl_sync_dataset_get(
    dataset_name: str,
    limit: int = Query(200, ge=1, le=2000),
    force_fixture: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Read-friendly sync trigger (viewer-safe) for demos / MCP smoke tests."""
    init_db()
    return trigger_dataset_sync(
        dataset_name,
        db=db,
        project_id=current_project_id(),
        limit=limit,
        force_fixture=force_fixture,
    )


@router.get("/etl/datasets")
def etl_list_datasets():
    return {"datasets": list(SUPPORTED_DATASETS)}


@router.get("/etl/mcn-benchmark")
def etl_mcn_benchmark():
    """Run CADEC/SMM4H-style MCN F1 benchmark (strict + relaxed)."""
    return run_mcn_benchmark()
