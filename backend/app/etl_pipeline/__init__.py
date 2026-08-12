"""Automated Data Ingestion & Validation Pipeline for VigilAI OMOP staging.

Pipelines:
* ``faers`` — openFDA FAERS JSON → PERSON / DRUG_EXPOSURE / CONDITION_OCCURRENCE
* ``sider`` — SIDER 4.1-style TSV → expected in-label baseline pairs
* ``athena_vocab`` — re-seed CONCEPT from RxE + MCN surrogates (BIGINT-safe)

Offline-first: live downloads degrade to bundled fixtures without crashing.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from .faers_ingestion import ingest_faers_to_omop
from .sider_ingestion import ingest_sider_baseline
from .athena_vocab import sync_athena_vocab_surrogates

SUPPORTED_DATASETS = ("faers", "sider", "athena_vocab")


def trigger_dataset_sync(
    dataset_name: str,
    *,
    db: Optional[Session] = None,
    project_id: Optional[int] = None,
    limit: int = 200,
    force_fixture: bool = False,
) -> dict[str, Any]:
    """Programmatic ETL entry used by FastMCP + API."""
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


__all__ = [
    "SUPPORTED_DATASETS",
    "trigger_dataset_sync",
    "ingest_faers_to_omop",
    "ingest_sider_baseline",
    "sync_athena_vocab_surrogates",
]
