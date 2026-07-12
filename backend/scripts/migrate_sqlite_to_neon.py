"""One-shot: copy local SQLite (backend/vigilai.db) → Neon Postgres.

Usage (from backend/):
  set DATABASE_URL=postgresql://...  (Neon pooled URL)
  .venv\\Scripts\\python.exe scripts\\migrate_sqlite_to_neon.py

Replaces Neon contents with SQLite (CASCADE truncate). Does not print secrets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

# Allow `python scripts/...` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BACKEND = Path(__file__).resolve().parents[1]
_SQLITE = _BACKEND / "vigilai.db"

# FK-safe order (parents → children)
_TABLE_ORDER = [
    "users",
    "projects",
    "monitored_queries",
    "pathfinder_runs",
    "suggested_sources",
    "raw_posts",
    "processed_posts",
    "signals",
    "alerts",
    "audit_logs",
    "forge_records",
]


def _pg_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url.startswith("postgres"):
        raise SystemExit("Set DATABASE_URL to your Neon postgresql://… URL first.")
    # psycopg2 is happier without channel_binding on some Windows builds
    return url.replace("&channel_binding=require", "").replace("?channel_binding=require&", "?").replace(
        "?channel_binding=require", ""
    )


def _copy_table(src: Engine, dst: Engine, table: str) -> int:
    insp_src = inspect(src)
    insp_dst = inspect(dst)
    if table not in insp_src.get_table_names():
        print(f"  skip {table} (missing in SQLite)")
        return 0
    if table not in insp_dst.get_table_names():
        print(f"  skip {table} (missing in Postgres — start API once to create schema)")
        return 0

    src_cols = {c["name"] for c in insp_src.get_columns(table)}
    dst_meta = {c["name"]: c for c in insp_dst.get_columns(table) if c["name"] in src_cols}
    dst_cols = list(dst_meta.keys())
    if not dst_cols:
        print(f"  skip {table} (no overlapping columns)")
        return 0

    bool_cols = {
        name
        for name, meta in dst_meta.items()
        if "BOOL" in str(meta["type"]).upper()
    }
    max_lens: dict[str, int] = {}
    for name, meta in dst_meta.items():
        t = meta["type"]
        length = getattr(t, "length", None)
        if length:
            max_lens[name] = int(length)

    def _coerce(row: dict) -> dict:
        out = {}
        for c in dst_cols:
            v = row[c]
            if c in bool_cols and v is not None:
                v = bool(int(v)) if not isinstance(v, bool) else v
            if isinstance(v, str):
                v = v.replace("\x00", "")
                if c in max_lens and len(v) > max_lens[c]:
                    v = v[: max_lens[c]]
            out[c] = v
        return out

    col_list = ", ".join(dst_cols)
    placeholders = ", ".join(f":{c}" for c in dst_cols)

    with src.connect() as sconn, dst.begin() as dconn:
        rows = sconn.execute(text(f"SELECT {col_list} FROM {table}")).mappings().all()
        if not rows:
            print(f"  {table}: 0 rows")
            return 0

        # Drop orphan alerts / FK children that would fail on Postgres
        if table == "alerts" and "signal_id" in dst_cols:
            valid = {
                r[0]
                for r in sconn.execute(text("SELECT id FROM signals")).fetchall()
            }
            before = len(rows)
            rows = [r for r in rows if r["signal_id"] in valid]
            skipped = before - len(rows)
            if skipped:
                print(f"  alerts: skipping {skipped} orphan rows (missing signal_id)")

        if table == "processed_posts" and "raw_id" in dst_cols:
            valid = {
                r[0]
                for r in sconn.execute(text("SELECT id FROM raw_posts")).fetchall()
            }
            before = len(rows)
            rows = [r for r in rows if r["raw_id"] in valid]
            skipped = before - len(rows)
            if skipped:
                print(f"  processed_posts: skipping {skipped} orphan rows")

        batch: list[dict] = []
        n = 0
        for row in rows:
            batch.append(_coerce(dict(row)))
            if len(batch) >= 200:
                dconn.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"), batch)
                n += len(batch)
                batch.clear()
        if batch:
            dconn.execute(text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"), batch)
            n += len(batch)

        try:
            dconn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                )
            )
        except Exception:
            pass

    print(f"  {table}: {n} rows")
    return n


def main() -> None:
    if not _SQLITE.is_file():
        raise SystemExit(f"SQLite not found: {_SQLITE}")

    pg = _pg_url()
    print(f"SQLite: {_SQLITE} ({_SQLITE.stat().st_size // 1024} KB)")
    print(f"Postgres host: {pg.split('@')[-1].split('/')[0]}")

    src = create_engine(f"sqlite:///{_SQLITE}", future=True)
    dst = create_engine(pg, future=True)

    # Ensure schema exists on Neon (idempotent)
    from app.database import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=dst)
    from app.database import migrate_schema

    # migrate_schema uses global engine — widen long text columns on Neon directly
    with dst.begin() as conn:
        for table, col in (
            ("raw_posts", "external_id"),
            ("raw_posts", "url"),
            ("raw_posts", "title"),
            ("raw_posts", "body"),
            ("raw_posts", "body_original"),
            ("suggested_sources", "url"),
            ("suggested_sources", "title"),
        ):
            try:
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT"))
            except Exception:
                pass

    with dst.begin() as conn:
        # Wipe Neon data (keep schema)
        existing = set(inspect(dst).get_table_names())
        for table in reversed(_TABLE_ORDER):
            if table in existing:
                conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        print("Neon truncated.")

    total = 0
    for table in _TABLE_ORDER:
        total += _copy_table(src, dst, table)

    print(f"Done. Copied ~{total} row inserts across tables.")
    with dst.connect() as c:
        for t in ("raw_posts", "signals", "alerts"):
            if t in inspect(dst).get_table_names():
                print(f"  verify {t}={c.execute(text(f'select count(*) from {t}')).scalar()}")


if __name__ == "__main__":
    main()
