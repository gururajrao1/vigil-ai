"""VigilAI Phase 1 — initialize OMOP CDM v5.4 + performance views on PostgreSQL.

Reads and executes:

* ``schemas/omop_v5_4_ddl.sql``
* ``schemas/performance_views.sql``

Usage::

    cd backend
    set DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/vigilai
    python -m app.db.init_db

``DATABASE_URL`` may also be a sync ``postgresql://`` / ``postgres://`` URL;
this script rewrites it to the ``postgresql+asyncpg://`` dialect automatically.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from .pg_url import create_async_engine_normalized

LOGGER = logging.getLogger("vigilai.db.init")

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
DDL_FILES: tuple[str, ...] = (
    "omop_v5_4_ddl.sql",
    "performance_views.sql",
)


def _configure_logging() -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def _strip_sql_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* … */`` blocks without touching strings."""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    cleaned_lines: List[str] = []
    for line in sql.splitlines():
        in_single = False
        in_double = False
        out: List[str] = []
        i = 0
        while i < len(line):
            ch = line[i]
            nxt = line[i + 1] if i + 1 < len(line) else ""
            if ch == "'" and not in_double:
                in_single = not in_single
                out.append(ch)
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                out.append(ch)
                i += 1
                continue
            if ch == "-" and nxt == "-" and not in_single and not in_double:
                break
            out.append(ch)
            i += 1
        cleaned_lines.append("".join(out))
    return "\n".join(cleaned_lines)


def _split_sql_statements(sql: str) -> List[str]:
    """Split a SQL script into executable statements.

    Handles PostgreSQL dollar-quoted bodies (``DO $$ … $$;``) so semicolons
    inside PL/pgSQL blocks are not treated as statement terminators.
    """
    cleaned = _strip_sql_comments(sql)
    statements: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(cleaned)
    in_single = False
    dollar_tag: str | None = None

    while i < n:
        ch = cleaned[i]

        if not in_single and ch == "$":
            m = re.match(r"\$([A-Za-z_]*)\$", cleaned[i:])
            if m:
                tag = m.group(0)
                if dollar_tag is None:
                    dollar_tag = tag
                    buf.append(tag)
                    i += len(tag)
                    continue
                if tag == dollar_tag:
                    buf.append(tag)
                    i += len(tag)
                    dollar_tag = None
                    continue

        if dollar_tag is not None:
            buf.append(ch)
            i += 1
            continue

        if ch == "'":
            buf.append(ch)
            if in_single and i + 1 < n and cleaned[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            in_single = not in_single
            i += 1
            continue

        if ch == ";" and not in_single:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def load_sql_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"SQL file not found: {path}")
    text_body = path.read_text(encoding="utf-8")
    if not text_body.strip():
        raise ValueError(f"SQL file is empty: {path}")
    return text_body


async def apply_sql_file(engine: AsyncEngine, path: Path) -> int:
    """Execute every statement in *path* under AUTOCOMMIT (DDL + REFRESH safe)."""
    sql = load_sql_file(path)
    statements = _split_sql_statements(sql)
    if not statements:
        raise RuntimeError(f"No executable statements found in {path.name}")

    LOGGER.info("Applying %s (%d statement(s))", path.name, len(statements))
    applied = 0

    async with engine.connect() as conn:
        # DDL, DO blocks, and REFRESH MATERIALIZED VIEW all need autocommit.
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for stmt in statements:
            upper = " ".join(stmt.split()).upper()
            preview = upper[:100]
            LOGGER.debug("→ %s%s", preview, "…" if len(upper) > 100 else "")
            await conn.execute(text(stmt))
            applied += 1
            if upper.startswith("REFRESH MATERIALIZED VIEW"):
                LOGGER.info("Materialized view refresh completed (%s)", path.name)

    return applied


async def verify_objects(engine: AsyncEngine) -> None:
    """Confirm core tables, partitions, and the materialized view exist."""
    checks = {
        "concept": """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'concept'
        """,
        "person": """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'person'
        """,
        "drug_exposure": """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'drug_exposure'
        """,
        "condition_occurrence": """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'condition_occurrence'
        """,
        "omop_signal_summary": """
            SELECT COUNT(*) FROM pg_matviews
            WHERE schemaname = 'public' AND matviewname = 'omop_signal_summary'
        """,
        "uq_omop_signal_summary_drug_condition": """
            SELECT COUNT(*) FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = 'uq_omop_signal_summary_drug_condition'
        """,
        "drug_exposure_partitions": """
            SELECT COUNT(*) FROM pg_inherits i
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'drug_exposure'
        """,
        "condition_occurrence_partitions": """
            SELECT COUNT(*) FROM pg_inherits i
            JOIN pg_class p ON p.oid = i.inhparent
            WHERE p.relname = 'condition_occurrence'
        """,
    }

    async with engine.connect() as conn:
        for label, sql in checks.items():
            result = await conn.execute(text(sql))
            value = int(result.scalar_one())
            if value <= 0:
                raise RuntimeError(f"Verification failed: {label} not found (count={value})")
            LOGGER.info("Verified %-42s → %s", label, value)

        # Expect yearly 2000-2030 (31) + DEFAULT (1) = 32 partitions each
        for parent in ("drug_exposure", "condition_occurrence"):
            result = await conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM pg_inherits i
                    JOIN pg_class p ON p.oid = i.inhparent
                    WHERE p.relname = :parent
                    """
                ),
                {"parent": parent},
            )
            n_parts = int(result.scalar_one())
            if n_parts < 32:
                raise RuntimeError(
                    f"Expected ≥32 partitions for {parent} (2000-2030 + DEFAULT), got {n_parts}"
                )
            LOGGER.info("Verified %-42s → %s partitions", f"{parent}_partition_count", n_parts)


async def init_omop_database(database_url: str | None = None) -> None:
    """Create OMOP CDM core tables, partitions, and performance views."""
    _configure_logging()
    load_dotenv()

    raw_url = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not raw_url:
        raise EnvironmentError(
            "DATABASE_URL is not set. Export a PostgreSQL URL, e.g. "
            "postgresql+asyncpg://vigilai:vigilai@127.0.0.1:5432/vigilai"
        )

    engine = create_async_engine_normalized(raw_url, echo=False)
    safe_url = make_url(str(engine.url)).render_as_string(hide_password=True)
    LOGGER.info("Connecting to %s", safe_url)
    try:
        for filename in DDL_FILES:
            path = SCHEMA_DIR / filename
            n = await apply_sql_file(engine, path)
            LOGGER.info("Finished %s (%d statement(s) applied)", filename, n)

        await verify_objects(engine)
        LOGGER.info("OMOP Phase 1 persistence layer initialized successfully.")
    except SQLAlchemyError as exc:
        LOGGER.exception("Database error while initializing OMOP schema: %s", exc)
        raise
    except Exception:
        LOGGER.exception("Unexpected failure during OMOP schema initialization")
        raise
    finally:
        await engine.dispose()
        LOGGER.info("Async engine disposed.")


def main() -> None:
    _configure_logging()
    try:
        asyncio.run(init_omop_database())
    except Exception as exc:  # noqa: BLE001 — CLI exit path
        LOGGER.error("init_db failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
