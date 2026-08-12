"""SQLAlchemy engine/session setup with additive schema migration.

`init_db()` calls `create_all` (creates missing tables) then `migrate_schema`
(adds any missing columns to existing tables). This means new model fields can
be added in models.py without ever wiping the database. Data is always preserved.
"""
from __future__ import annotations

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

logger = logging.getLogger("vigilai.database")

_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 60} if _is_sqlite else {}

# Neon/Postgres: recycle + pre-ping so idle SSL drops don't 500 /api/signals.
_engine_kwargs: dict = {"connect_args": connect_args, "future": True}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_recycle=280,
        pool_size=5,
        max_overflow=10,
    )

engine = create_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=60000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _col_default_ddl(col) -> str:
    """Return a safe SQL DEFAULT clause for a column type."""
    type_name = type(col.type).__name__.upper()
    if "INT" in type_name:
        return "DEFAULT 0"
    if any(t in type_name for t in ("FLOAT", "NUMERIC", "REAL")):
        return "DEFAULT 0.0"
    if "BOOL" in type_name:
        return "DEFAULT 0"
    return "DEFAULT NULL"


def migrate_schema() -> None:
    """Add missing columns to existing tables — never drops or alters existing data.

    Iterates over every SQLAlchemy-mapped table and column. For each column that
    is defined in the model but absent from the live database schema, issues an
    ALTER TABLE ADD COLUMN. Safe to run repeatedly (idempotent).

    On PostgreSQL also widens a few VARCHAR columns that SQLite never enforced
    (Google News external_id / long article URLs).
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all handles genuinely new tables
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                try:
                    default = _col_default_ddl(col)
                    nullable = "" if col.nullable else ""  # keep nullable for ADD COLUMN compat
                    ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type} {default}"
                    conn.execute(text(ddl))
                    logger.info("migrate_schema: added column %s.%s", table.name, col.name)
                except Exception as exc:
                    # Column may already exist in a race; log and continue
                    logger.debug("migrate_schema skip %s.%s: %s", table.name, col.name, exc)

        if not _is_sqlite:
            _widen_postgres_varchars(conn)
            _widen_omop_concept_ids_to_bigint(conn)
            _ensure_alerts_signal_cascade(conn)


def _widen_postgres_varchars(conn) -> None:
    """Widen columns that can exceed historical SQLite-era VARCHAR lengths."""
    text_cols = (
        ("raw_posts", "external_id"),
        ("raw_posts", "url"),
        ("raw_posts", "title"),
        ("suggested_sources", "url"),
        ("suggested_sources", "title"),
    )
    for table, col in text_cols:
        try:
            conn.execute(text(f'ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT'))
            logger.info("migrate_schema: widened %s.%s to TEXT", table, col)
        except Exception as exc:
            logger.debug("migrate_schema widen skip %s.%s: %s", table, col, exc)


def _widen_omop_concept_ids_to_bigint(conn) -> None:
    """Promote OMOP concept_id columns to BIGINT (RxE / Athena overflow fix).

    Mirrors ``backend/app/db/init_db.sql``. Idempotent on Postgres.
    """
    alters = (
        ("omop_concept", "concept_id"),
        ("omop_person", "gender_concept_id"),
        ("omop_person", "race_concept_id"),
        ("omop_person", "ethnicity_concept_id"),
        ("omop_person", "gender_source_concept_id"),
        ("omop_person", "race_source_concept_id"),
        ("omop_person", "ethnicity_source_concept_id"),
        ("omop_drug_exposure", "drug_concept_id_int"),
        ("omop_drug_exposure", "drug_type_concept_id"),
        ("omop_drug_exposure", "route_concept_id"),
        ("omop_drug_exposure", "drug_source_concept_id"),
        ("omop_condition_occurrence", "condition_concept_id_int"),
        ("omop_condition_occurrence", "condition_type_concept_id"),
        ("omop_condition_occurrence", "condition_status_concept_id"),
        ("omop_condition_occurrence", "condition_source_concept_id"),
        ("omop_drug_condition_baseline", "drug_concept_id"),
        ("omop_drug_condition_baseline", "condition_concept_id"),
    )
    for table, col in alters:
        try:
            conn.execute(
                text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE BIGINT")
            )
            logger.info("migrate_schema: %s.%s → BIGINT", table, col)
        except Exception as exc:
            logger.debug("migrate_schema BIGINT skip %s.%s: %s", table, col, exc)


def _ensure_alerts_signal_cascade(conn) -> None:
    """Recreate alerts.signal_id FK with ON DELETE CASCADE (Neon/Postgres).

    Legacy schema lacked CASCADE, so signal rebuilds failed with IntegrityError
    when orphan alerts still pointed at deleted signal rows.
    """
    try:
        rows = conn.execute(text(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'alerts'::regclass AND contype = 'f'
              AND pg_get_constraintdef(oid) ILIKE '%signal_id%'
            """
        )).fetchall()
        for (conname,) in rows:
            conn.execute(text(f'ALTER TABLE alerts DROP CONSTRAINT IF EXISTS "{conname}"'))
        conn.execute(text(
            """
            ALTER TABLE alerts
            ADD CONSTRAINT alerts_signal_id_fkey
            FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE
            """
        ))
        logger.info("migrate_schema: alerts.signal_id FK set to ON DELETE CASCADE")
    except Exception as exc:
        logger.debug("migrate_schema alerts cascade skip: %s", exc)


def checkpoint_wal() -> None:
    """Force a full WAL checkpoint so pending writes are flushed into the main DB file.

    Must be called before `create_all` / `migrate_schema` so schema operations
    see a consistent view, and called on shutdown so no data sits only in the WAL.
    Only meaningful for SQLite — no-op for PostgreSQL.
    """
    if not _is_sqlite:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        logger.info("WAL checkpoint complete")
    except Exception as exc:
        logger.warning("WAL checkpoint failed (non-fatal): %s", exc)


def init_db() -> None:
    from . import models  # noqa: F401  (ensure models are registered)
    from .db import omop_models  # noqa: F401  (OMOP CDM v5.4 Module 3)
    from .db.schemas import omop_cdm  # noqa: F401  (device exposure + re-exports)

    checkpoint_wal()                        # flush any pending WAL data first
    Base.metadata.create_all(bind=engine)  # creates missing tables
    migrate_schema()                        # adds missing columns to existing tables
