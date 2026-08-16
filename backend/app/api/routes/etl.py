"""ETL pipeline API — FAERS / SIDER / Athena-vocab sync + openFDA bulk downloads."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db, init_db
from ...etl_pipeline import SUPPORTED_DATASETS, trigger_dataset_sync
from ...etl_pipeline.download_openfda import (
    DOWNLOAD_INDEX_URL,
    download_partitions,
    list_partitions,
    summarize_partitions,
)
from ...etl_pipeline.stream_ingest_openfda import get_job, list_jobs, start_job
from ...nlp.validation import run_mcn_benchmark
from ...projects.scope import current_project_id

router = APIRouter(tags=["etl"])

DomainLiteral = Literal["drug", "device", "both"]


class OpenFdaDownloadBody(BaseModel):
    domain: DomainLiteral = "both"
    out_dir: str = Field(
        ...,
        description="Absolute or relative folder for drug/event and device/event JSON",
        examples=["C:/Users/Gururaja/Data/vigilai/openfda"],
    )
    limit: Optional[int] = Field(
        None, ge=1, description="Max partitions to download (omit = all ~2k)"
    )
    offset: int = Field(0, ge=0)
    workers: int = Field(4, ge=1, le=16)
    skip_existing: bool = True
    background: bool = Field(
        False,
        description="If true, start download in a BackgroundTask and return immediately",
    )


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


@router.get("/etl/openfda/partitions")
def etl_openfda_partitions(
    domain: DomainLiteral = Query("both"),
    include_files: bool = Query(
        False, description="If true, include every partition URL (large payload)"
    ),
):
    """List openFDA bulk download partitions for drug (FAERS) and/or device (MAUDE).

    Source of truth: ``https://api.fda.gov/download.json``
    (``results.drug.event`` + ``results.device.event``).
    """
    try:
        parts = list_partitions(domain)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"openFDA download.json unreachable: {exc}") from exc
    summary = summarize_partitions(parts)
    if not include_files:
        summary.pop("partitions", None)
        summary["hint"] = (
            "Pass include_files=true for full partition list. Prefer "
            "POST /api/etl/openfda/stream-ingest (CDN → posts/OMOP, no full download). "
            "Optional disk mirror: POST /api/etl/openfda/download"
        )
    summary["endpoints"] = {
        "index": DOWNLOAD_INDEX_URL,
        "drug_event_api": "https://api.fda.gov/drug/event.json",
        "device_event_api": "https://api.fda.gov/device/event.json",
    }
    return summary


class OpenFdaStreamIngestBody(BaseModel):
    domain: DomainLiteral = "both"
    max_partitions: Optional[int] = Field(
        5,
        description="Partition files to pull from CDN (null/omit with care; 0 = all ~2k)",
    )
    offset: int = Field(0, ge=0)
    event_limit: Optional[int] = Field(
        50_000, description="Stop after N events across partitions (0 = unlimited)"
    )
    batch_size: int = Field(500, ge=50, le=5000)
    also_posts: bool = Field(True, description="Write Overview raw_posts (required for metrics)")
    also_omop: bool = Field(True, description="Write OMOP staging for drug partitions")
    recompute_signals: bool = True
    project_id: Optional[int] = None
    background: bool = Field(
        True,
        description="Run in a background thread and return job_id (recommended)",
    )


@router.post("/etl/openfda/download")
def etl_openfda_download(body: OpenFdaDownloadBody, background: BackgroundTasks):
    """Download openFDA drug/device event partition JSON (unzipped) to ``out_dir``.

    Prefer ``POST /api/etl/openfda/stream-ingest`` to ingest without saving all files.
    """
    out = Path(body.out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot create out_dir: {exc}") from exc

    kwargs = dict(
        domain=body.domain,
        out_dir=out,
        limit=body.limit,
        offset=body.offset,
        workers=body.workers,
        skip_existing=body.skip_existing,
    )

    if body.background:
        background.add_task(download_partitions, **kwargs)
        return {
            "ok": True,
            "started": True,
            "background": True,
            "message": "Download started in background",
            **{k: (str(v) if k == "out_dir" else v) for k, v in kwargs.items()},
            "layout": {
                "drug": str((out / "drug" / "event").resolve()),
                "device": str((out / "device" / "event").resolve()),
            },
        }

    try:
        return download_partitions(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Download failed: {exc}") from exc


@router.post("/etl/openfda/stream-ingest")
def etl_openfda_stream_ingest(body: OpenFdaStreamIngestBody):
    """Fetch openFDA partition URLs and ingest directly (no full disk mirror).

    Each of the ~2k ``download.json`` partitions is HTTP-GETed, parsed, and
    flushed into ``raw_posts`` (Overview metrics) and optionally OMOP staging.
    """
    max_p = body.max_partitions
    if max_p == 0:
        max_p = None
    ev_lim = body.event_limit
    if ev_lim == 0:
        ev_lim = None

    kwargs = dict(
        domain=body.domain,
        max_partitions=max_p,
        offset=body.offset,
        event_limit=ev_lim,
        batch_size=body.batch_size,
        also_posts=body.also_posts,
        also_omop=body.also_omop,
        recompute_signals=body.recompute_signals,
        project_id=body.project_id if body.project_id is not None else current_project_id(),
    )

    if body.background:
        job = start_job(**kwargs)
        return {
            "ok": True,
            "started": True,
            "background": True,
            "job_id": job.job_id,
            "status_url": f"/api/etl/openfda/stream-ingest/{job.job_id}",
            "job": job.to_dict(),
        }

    from ...etl_pipeline.stream_ingest_openfda import stream_ingest_openfda

    try:
        return stream_ingest_openfda(**kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Stream ingest failed: {exc}") from exc


@router.get("/etl/openfda/stream-ingest")
def etl_openfda_stream_ingest_list(limit: int = Query(20, ge=1, le=100)):
    """List recent openFDA stream-ingest jobs."""
    return {"jobs": list_jobs(limit=limit)}


@router.get("/etl/openfda/stream-ingest/{job_id}")
def etl_openfda_stream_ingest_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return job.to_dict()
