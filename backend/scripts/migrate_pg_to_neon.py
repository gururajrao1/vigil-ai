"""Copy Railway (or any) Postgres → Neon Postgres without printing secrets.

Usage (from backend/):
  set SOURCE_DATABASE_URL=postgresql://…   # Railway DATABASE_PUBLIC_URL
  set DATABASE_URL=postgresql://…          # Neon pooled URL
  .venv\\Scripts\\python.exe scripts\\migrate_pg_to_neon.py

Or pass file paths:
  .venv\\Scripts\\python.exe scripts\\migrate_pg_to_neon.py --src-file _railway_url.tmp --dst-file _neon_url.tmp
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("postgres"):
        raise SystemExit("Need a postgresql:// URL")
    url = (
        url.replace("&channel_binding=require", "")
        .replace("?channel_binding=require&", "?")
        .replace("?channel_binding=require", "")
    )
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _host(url: str) -> str:
    return url.split("@")[-1].split("/")[0]


def _copy_table(src: Engine, dst: Engine, table: str) -> int:
    insp_src = inspect(src)
    insp_dst = inspect(dst)
    if table not in insp_src.get_table_names():
        print(f"  skip {table} (missing in source)")
        return 0
    if table not in insp_dst.get_table_names():
        print(f"  skip {table} (missing in destination)")
        return 0

    src_cols = {c["name"] for c in insp_src.get_columns(table)}
    dst_meta = {c["name"]: c for c in insp_dst.get_columns(table) if c["name"] in src_cols}
    dst_cols = list(dst_meta.keys())
    if not dst_cols:
        print(f"  skip {table} (no overlapping columns)")
        return 0

    bool_cols = {
        name for name, meta in dst_meta.items() if "BOOL" in str(meta["type"]).upper()
    }
    max_lens: dict[str, int] = {}
    for name, meta in dst_meta.items():
        length = getattr(meta["type"], "length", None)
        if length:
            max_lens[name] = int(length)

    def _coerce(row: dict) -> dict:
        out = {}
        for c in dst_cols:
            v = row[c]
            if c in bool_cols and v is not None and not isinstance(v, bool):
                v = bool(v)
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

        batch: list[dict] = []
        n = 0
        for row in rows:
            batch.append(_coerce(dict(row)))
            if len(batch) >= 150:
                dconn.execute(
                    text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"),
                    batch,
                )
                n += len(batch)
                batch.clear()
        if batch:
            dconn.execute(
                text(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"),
                batch,
            )
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-file", default="")
    ap.add_argument("--dst-file", default="")
    args = ap.parse_args()

    src_url = os.getenv("SOURCE_DATABASE_URL", "").strip()
    dst_url = os.getenv("DATABASE_URL", "").strip()
    if args.src_file:
        src_url = Path(args.src_file).read_text(encoding="utf-8").strip()
    if args.dst_file:
        dst_url = Path(args.dst_file).read_text(encoding="utf-8").strip()

    src_url = _clean_url(src_url)
    dst_url = _clean_url(dst_url)

    print(f"Source: {_host(src_url)}")
    print(f"Dest:   {_host(dst_url)}")

    src = create_engine(src_url, future=True)
    dst = create_engine(dst_url, future=True)

    from app.database import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=dst)
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
        existing = set(inspect(dst).get_table_names())
        for table in reversed(_TABLE_ORDER):
            if table in existing:
                conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        print("Neon truncated.")

    total = 0
    for table in _TABLE_ORDER:
        total += _copy_table(src, dst, table)

    print(f"Done. Copied ~{total} row inserts.")
    with dst.connect() as c:
        for t in ("raw_posts", "signals", "users", "projects"):
            if t in inspect(dst).get_table_names():
                print(f"  verify {t}={c.execute(text(f'select count(*) from {t}')).scalar()}")


if __name__ == "__main__":
    main()
