"""Fast local signal recompute (SQLite preferred; no openFDA / narratives / heavy overlays).

Usage (from backend/):
  # Against a local dump (recommended):
  .venv\\Scripts\\python.exe scripts\\_run_recompute_offline.py --sqlite data/vigilai_local_recompute.db

  # Against whatever DATABASE_URL points at (Neon — slow; avoid for FAERS-scale tests):
  .venv\\Scripts\\python.exe scripts\\_run_recompute_offline.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, event, inspect, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def _counts(db) -> dict:
    return {
        "posts": int(db.execute(text("SELECT COUNT(*) FROM raw_posts")).scalar() or 0),
        "ae_posts": int(
            db.execute(
                text("SELECT COUNT(*) FROM processed_posts WHERE ae_flag = 1 OR ae_flag = true")
            ).scalar()
            or 0
        ),
        "signals": int(db.execute(text("SELECT COUNT(*) FROM signals")).scalar() or 0),
    }


def _heal_sqlite_writable_tables(engine) -> None:
    """PG→SQLite dumps omit PRIMARY KEY, so ORM inserts get NULL identity.

    Drop and recreate writable analytics tables from SQLAlchemy models so
    ``signals.id`` / ``alerts.id`` / ``audit_logs.id`` autoincrement correctly.
    Raw/processed corpus tables are left untouched.
    """
    from app.database import Base  # noqa: E402
    from app.models import Alert, AuditLog, Signal, SignalSnapshot  # noqa: E402

    tables = [Alert.__table__, SignalSnapshot.__table__, Signal.__table__, AuditLog.__table__]
    # Drop dependents first (alerts → signals).
    drop_order = ["alerts", "signal_snapshots", "signals", "audit_logs"]
    with engine.begin() as conn:
        for name in drop_order:
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    Base.metadata.create_all(bind=engine, tables=tables)
    insp = inspect(engine)
    for t in ("signals", "alerts", "audit_logs"):
        pk = insp.get_pk_constraint(t).get("constrained_columns") or []
        print(f"schema heal: {t} pk={pk}", flush=True)


def _session_for(sqlite_path: str | None):
    if sqlite_path:
        p = Path(sqlite_path)
        if not p.is_absolute():
            p = Path(__file__).resolve().parents[1] / p
        if not p.exists():
            raise SystemExit(f"SQLite file not found: {p}")
        url = f"sqlite:///{p.as_posix()}"
        engine = create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 60}, future=True
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=60000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        # Capture pre-heal signal count (dump tables lack PK; heal drops signals).
        with engine.connect() as conn:
            try:
                pre_heal_signals = int(
                    conn.execute(text("SELECT COUNT(*) FROM signals")).scalar() or 0
                )
            except Exception:
                pre_heal_signals = 0
            posts = int(conn.execute(text("SELECT COUNT(*) FROM raw_posts")).scalar() or 0)
            ae_posts = int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM processed_posts "
                        "WHERE ae_flag = 1 OR ae_flag = true"
                    )
                ).scalar()
                or 0
            )
        print(
            f"PRE-HEAL corpus posts={posts} ae_posts={ae_posts} signals={pre_heal_signals}",
            flush=True,
        )
        _heal_sqlite_writable_tables(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        return Session(), str(p), {
            "posts": posts,
            "ae_posts": ae_posts,
            "signals": pre_heal_signals,
        }

    from app.database import SessionLocal  # noqa: E402

    db = SessionLocal()
    before = _counts(db)
    return db, os.getenv("DATABASE_URL", "(DATABASE_URL)")[:80], before


def main() -> None:
    ap = argparse.ArgumentParser(description="Fast offline signal recompute")
    ap.add_argument(
        "--sqlite",
        default="",
        help="Local SQLite path (relative to backend/). Prefer this over Neon.",
    )
    ap.add_argument(
        "--no-fast",
        action="store_true",
        help="Disable fast path (run full overlays).",
    )
    args = ap.parse_args()

    from app.pipeline import recompute_signals  # noqa: E402

    db, target, before = _session_for(args.sqlite or None)
    fast = not args.no_fast
    print(f"target={target}", flush=True)
    print(
        f"flags: use_fda=False with_narrative=False fast={fast} with_overlays={not fast}",
        flush=True,
    )
    print(f"BEFORE {before}", flush=True)
    t0 = time.perf_counter()
    try:
        stats = recompute_signals(
            db,
            use_fda=False,
            with_narrative=False,
            fast=fast,
            with_overlays=not fast,
        )
        elapsed = time.perf_counter() - t0
        after = _counts(db)
        print(f"DONE stats={stats} elapsed_s={elapsed:.1f}", flush=True)
        print(f"AFTER  {after}", flush=True)
        print(
            f"DELTA  signals {before['signals']} -> {after['signals']} "
            f"({after['signals'] - before['signals']:+d})",
            flush=True,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
