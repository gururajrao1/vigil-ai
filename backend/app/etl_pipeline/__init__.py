"""Automated Data Ingestion & Validation Pipeline for VigilAI OMOP staging.

Legacy session-based helpers (``faers`` / ``sider`` / ``athena_vocab``) remain for
FastMCP + API. Phase 2 CLI modules:

* ``load_athena_vocab`` — Athena CONCEPT → ``omop_concept``
* ``load_sider`` — SIDER 4.1 → in-label ``omop_drug_condition_baseline``
* ``ingest_faers`` — streaming FAERS JSON → person / drug / condition
* ``run_pipeline`` — orchestrator + ``REFRESH MATERIALIZED VIEW CONCURRENTLY``

Offline-first: live downloads degrade to bundled fixtures without crashing.

Imports of session-based helpers are **lazy** so CLI modules
(``python -m app.etl_pipeline.ingest_faers``) do not construct the sync
SQLAlchemy engine (or require ``psycopg2``) at import time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SUPPORTED_DATASETS = ("faers", "sider", "athena_vocab")


def trigger_dataset_sync(
    dataset_name: str,
    *,
    db: Optional["Session"] = None,
    project_id: Optional[int] = None,
    limit: int = 200,
    force_fixture: bool = False,
) -> dict[str, Any]:
    """Programmatic ETL entry used by FastMCP + API."""
    from .athena_vocab import sync_athena_vocab_surrogates
    from .faers_ingestion import ingest_faers_to_omop
    from .sider_ingestion import ingest_sider_baseline

    name = (dataset_name or "").strip().lower()
    if name not in SUPPORTED_DATASETS:
        return {
            "ok": False,
            "dataset": dataset_name,
            "error": f"Unknown dataset. Supported: {', '.join(SUPPORTED_DATASETS)}",
        }

    own_session = db is None
    if own_session:
        from ..database import SessionLocal, init_db

        init_db()
        db = SessionLocal()

    try:
        if name == "faers":
            result = ingest_faers_to_omop(
                db,
                project_id=project_id,
                limit=limit,
                force_fixture=force_fixture,
            )
        elif name == "sider":
            result = ingest_sider_baseline(
                db,
                project_id=project_id,
                force_fixture=force_fixture,
            )
        else:
            result = sync_athena_vocab_surrogates(db)
        return {"ok": True, "dataset": name, **result}
    except Exception as exc:  # noqa: BLE001 — never crash MCP/API callers
        if db is not None:
            db.rollback()
        return {
            "ok": False,
            "dataset": name,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if own_session and db is not None:
            db.close()


def __getattr__(name: str) -> Any:
    """Lazy re-exports for backwards-compatible ``from app.etl_pipeline import …``."""
    if name == "ingest_faers_to_omop":
        from .faers_ingestion import ingest_faers_to_omop

        return ingest_faers_to_omop
    if name == "ingest_sider_baseline":
        from .sider_ingestion import ingest_sider_baseline

        return ingest_sider_baseline
    if name == "sync_athena_vocab_surrogates":
        from .athena_vocab import sync_athena_vocab_surrogates

        return sync_athena_vocab_surrogates
    if name == "run_phase2_pipeline":
        return run_phase2_pipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def run_phase2_pipeline(**kwargs: Any) -> dict[str, Any]:
    """Async Phase 2 orchestrator wrapper for programmatic callers."""
    import asyncio

    from .run_pipeline import run_pipeline

    return asyncio.run(run_pipeline(**kwargs))


__all__ = [
    "SUPPORTED_DATASETS",
    "trigger_dataset_sync",
    "ingest_faers_to_omop",
    "ingest_sider_baseline",
    "sync_athena_vocab_surrogates",
    "run_phase2_pipeline",
]
