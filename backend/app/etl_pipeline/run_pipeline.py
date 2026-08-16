"""Phase 2 ETL entry-point: Athena → SIDER → FAERS → matview refresh.

Orchestrates vocabulary load, in-label baseline ingestion, FAERS streaming
ingest, then refreshes ``omop_signal_summary`` concurrently so disproportionality
dashboards see cumulative counts without locking readers.

Usage::

    python -m app.etl_pipeline.run_pipeline
    python -m app.etl_pipeline.run_pipeline --concept-csv /data/CONCEPT.csv \\
        --sider-tsv /data/meddra_all_label_se.tsv --faers-json /data/faers/
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from dotenv import load_dotenv
from sqlalchemy import text

from .ingest_faers import ingest_faers
from .load_athena_vocab import load_athena_vocab
from .load_sider import load_sider
from ..db.pg_url import create_async_engine_normalized

LOGGER = logging.getLogger("vigilai.etl.run_pipeline")

# Matview over OMOP *staging* tables populated by Phase 2 loaders.
ENSURE_SIGNAL_SUMMARY_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS omop_signal_summary AS
SELECT
    COALESCE(de.drug_concept_id_int, 0) AS drug_concept_id,
    COALESCE(co.condition_concept_id_int, 0) AS condition_concept_id,
    COUNT(DISTINCT de.person_id) AS exposure_count
FROM omop_drug_exposure AS de
INNER JOIN omop_condition_occurrence AS co
    ON co.person_id = de.person_id
GROUP BY
    COALESCE(de.drug_concept_id_int, 0),
    COALESCE(co.condition_concept_id_int, 0)
WITH NO DATA
"""


def _configure_logging(verbose: bool = False) -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOGGER.propagate = False


async def refresh_signal_summary(*, database_url: Optional[str] = None) -> dict[str, Any]:
    """Ensure staging-backed ``omop_signal_summary``, then CONCURRENTLY refresh."""
    load_dotenv()
    raw = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not raw:
        raise EnvironmentError("DATABASE_URL is required for matview refresh")

    engine = create_async_engine_normalized(raw)
    mode = "concurrent"
    try:
        async with engine.begin() as conn:
            exists = await conn.execute(
                text(
                    """
                    SELECT definition FROM pg_matviews
                    WHERE schemaname = current_schema()
                      AND matviewname = 'omop_signal_summary'
                    """
                )
            )
            row = exists.first()
            needs_create = row is None
            # Phase 1 DDL may have pointed at unprefixed CDM tables; Phase 2 loads omop_*
            if row is not None and "omop_drug_exposure" not in (row[0] or "").lower():
                LOGGER.info(
                    "Recreating omop_signal_summary to join omop_drug_exposure / "
                    "omop_condition_occurrence"
                )
                await conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS omop_signal_summary CASCADE"))
                needs_create = True

            if needs_create:
                LOGGER.info("Creating omop_signal_summary materialized view (omop_* staging)")
                await conn.execute(
                    text(ENSURE_SIGNAL_SUMMARY_SQL.replace("IF NOT EXISTS ", ""))
                )
                await conn.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS
                        uq_omop_signal_summary_drug_condition
                        ON omop_signal_summary (drug_concept_id, condition_concept_id)
                        """
                    )
                )
                await conn.execute(text("REFRESH MATERIALIZED VIEW omop_signal_summary"))
                mode = "initial"
            else:
                await conn.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS
                        uq_omop_signal_summary_drug_condition
                        ON omop_signal_summary (drug_concept_id, condition_concept_id)
                        """
                    )
                )

        if mode == "concurrent":
            # CONCURRENTLY cannot run inside a transaction block
            async with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                try:
                    await conn.execute(
                        text("REFRESH MATERIALIZED VIEW CONCURRENTLY omop_signal_summary")
                    )
                    LOGGER.info("Refreshed omop_signal_summary CONCURRENTLY")
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "CONCURRENTLY refresh failed (%s) — falling back to blocking refresh",
                        exc,
                    )
                    await conn.execute(text("REFRESH MATERIALIZED VIEW omop_signal_summary"))
                    mode = "blocking_fallback"

        async with engine.connect() as conn:
            count_row = await conn.execute(
                text("SELECT COUNT(*) FROM omop_signal_summary")
            )
        n = int(count_row.scalar_one())
        return {"view": "omop_signal_summary", "refresh_mode": mode, "row_count": n}
    finally:
        await engine.dispose()


async def run_pipeline(
    *,
    concept_csv: Optional[Path] = None,
    sider_tsv: Optional[Path] = None,
    faers_json: Optional[Path] = None,
    database_url: Optional[str] = None,
    project_id: Optional[int] = None,
    faers_limit: int = 50_000,
    faers_batch_size: int = 5_000,
    force_fixture: bool = False,
    skip_athena: bool = False,
    skip_sider: bool = False,
    skip_faers: bool = False,
    skip_refresh: bool = False,
) -> dict[str, Any]:
    """Execute Phase 2 steps in order; return per-step result dicts."""
    summary: dict[str, Any] = {"ok": True, "steps": {}}

    if not skip_athena:
        LOGGER.info("=== Step 1/4: Athena vocabulary → omop_concept ===")
        # load_athena_vocab is sync (pandas + SQLAlchemy sync engine)
        athena_result = await asyncio.to_thread(
            load_athena_vocab,
            concept_csv=concept_csv,
            database_url=database_url,
            fallback_surrogates=True,
        )
        summary["steps"]["athena"] = athena_result
        LOGGER.info("Athena complete: %s", athena_result)
    else:
        summary["steps"]["athena"] = {"skipped": True}

    if not skip_sider:
        LOGGER.info("=== Step 2/4: SIDER 4.1 in-label baseline ===")
        sider_result = await load_sider(
            sider_tsv=sider_tsv,
            database_url=database_url,
            project_id=project_id,
            force_fixture=force_fixture,
        )
        summary["steps"]["sider"] = sider_result
        LOGGER.info("SIDER complete: %s", sider_result)
    else:
        summary["steps"]["sider"] = {"skipped": True}

    if not skip_faers:
        LOGGER.info("=== Step 3/4: FAERS / openFDA JSON ingest ===")
        faers_result = await ingest_faers(
            faers_json=faers_json,
            database_url=database_url,
            limit=faers_limit,
            batch_size=faers_batch_size,
            project_id=project_id,
            force_fixture=force_fixture,
        )
        summary["steps"]["faers"] = faers_result
        LOGGER.info("FAERS complete: %s", faers_result)
    else:
        summary["steps"]["faers"] = {"skipped": True}

    if not skip_refresh:
        LOGGER.info("=== Step 4/4: REFRESH omop_signal_summary ===")
        refresh_result = await refresh_signal_summary(database_url=database_url)
        summary["steps"]["refresh"] = refresh_result
        LOGGER.info("Refresh complete: %s", refresh_result)
    else:
        summary["steps"]["refresh"] = {"skipped": True}

    return summary


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="VigilAI Phase 2 ETL orchestrator (Athena -> SIDER -> FAERS -> refresh)"
    )
    parser.add_argument("--concept-csv", type=Path, default=None)
    parser.add_argument("--sider-tsv", type=Path, default=None)
    parser.add_argument("--faers-json", type=Path, default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--faers-limit", type=int, default=50_000)
    parser.add_argument("--faers-batch-size", type=int, default=5_000)
    parser.add_argument("--force-fixture", action="store_true")
    parser.add_argument("--skip-athena", action="store_true")
    parser.add_argument("--skip-sider", action="store_true")
    parser.add_argument("--skip-faers", action="store_true")
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)

    try:
        result = asyncio.run(
            run_pipeline(
                concept_csv=args.concept_csv,
                sider_tsv=args.sider_tsv,
                faers_json=args.faers_json,
                database_url=args.database_url,
                project_id=args.project_id,
                faers_limit=args.faers_limit,
                faers_batch_size=args.faers_batch_size,
                force_fixture=args.force_fixture,
                skip_athena=args.skip_athena,
                skip_sider=args.skip_sider,
                skip_faers=args.skip_faers,
                skip_refresh=args.skip_refresh,
            )
        )
        LOGGER.info("Pipeline finished: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("run_pipeline failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
