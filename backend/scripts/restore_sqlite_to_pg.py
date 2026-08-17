"""Restore a SQLite dump (from dump_pg_to_sqlite.py) into a Postgres DATABASE_URL.

Usage (from backend/):
  set DATABASE_URL=postgresql://…supabase…:6543/postgres?sslmode=require
  .venv\\Scripts\\python.exe scripts\\restore_sqlite_to_pg.py --sqlite data/vigilai_neon_backup.db
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from app.db.pg_url import normalize_database_url  # noqa: E402

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
    "signal_snapshots",
    "omop_concept",
    "omop_person",
    "omop_drug_exposure",
    "omop_condition_occurrence",
    "omop_device_exposure",
    "omop_drug_condition_baseline",
]


def _clean_pg(url: str) -> str:
    url = normalize_database_url((url or "").strip(), is_async=False)
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
        print(f"  skip {table} (missing in sqlite)")
        return 0
    if table not in insp_dst.get_table_names():
        print(f"  skip {table} (missing in postgres — create_all first)")
        return 0

    src_cols = {c["name"] for c in insp_src.get_columns(table)}
    dst_meta = {c["name"]: c for c in insp_dst.get_columns(table) if c["name"] in src_cols}
    dst_cols = list(dst_meta.keys())
    if not dst_cols:
        return 0

    bool_cols = {
        name for name, meta in dst_meta.items() if "BOOL" in str(meta["type"]).upper()
    }
    max_lens: dict[str, int] = {}
    for name, meta in dst_meta.items():
        length = getattr(meta["type"], "length", None)
        if length:
            max_lens[name] = int(length)

    col_list = ", ".join(dst_cols)
    placeholders = ", ".join(f":{c}" for c in dst_cols)
    with src.connect() as sconn:
        rows = sconn.execute(text(f'SELECT {", ".join(chr(34)+c+chr(34) for c in dst_cols)} FROM "{table}"')).mappings().all()

    if not rows:
        print(f"  {table}: 0")
        return 0

    def _coerce(row: dict) -> dict:
        out = {}
        for c in dst_cols:
            v = row[c]
            if c in bool_cols and v is not None and not isinstance(v, bool):
                v = bool(int(v)) if str(v).isdigit() else bool(v)
            if isinstance(v, str):
                v = v.replace("\x00", "")
                if c in max_lens and len(v) > max_lens[c]:
                    v = v[: max_lens[c]]
            out[c] = v
        return out

    with dst.begin() as dconn:
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
    print(f"  {table}: {n}", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="data/vigilai_neon_backup.db")
    ap.add_argument("--dst-file", default="")
    args = ap.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_absolute():
        sqlite_path = Path(__file__).resolve().parents[1] / sqlite_path
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite dump: {sqlite_path}")

    dst_url = os.getenv("DATABASE_URL", "").strip()
    if args.dst_file:
        dst_url = Path(args.dst_file).read_text(encoding="utf-8").strip()
    dst_url = _clean_pg(dst_url)
    if "neon.tech" in dst_url.lower():
        raise SystemExit("Refusing to restore into Neon — set DATABASE_URL to Supabase/Render Postgres.")

    print(f"SQLite: {sqlite_path}")
    print(f"Dest:   {_host(dst_url)}")

    src = create_engine(f"sqlite:///{sqlite_path.as_posix()}", future=True)
    dst = create_engine(dst_url, future=True, pool_pre_ping=True)

    from app.database import Base
    import app.models  # noqa: F401
    from app.db import omop_models as _omop  # noqa: F401

    Base.metadata.create_all(bind=dst)
    # OMOP staging uses the same app.database.Base in omop_models
    try:
        _omop.Base.metadata.create_all(bind=dst)
    except Exception:
        pass
    # Device exposure may live on schemas Base
    try:
        from app.db.schemas import omop_cdm as _cdm  # noqa: F401

        _cdm.Base.metadata.create_all(bind=dst)
    except Exception:
        pass

    with dst.begin() as conn:
        existing = set(inspect(dst).get_table_names())
        # Truncate known order first
        for table in reversed(_TABLE_ORDER):
            if table in existing:
                try:
                    conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
                except Exception:
                    conn.execute(text(f"DELETE FROM {table}"))
        print("Destination truncated.", flush=True)

    total = 0
    for table in _TABLE_ORDER:
        total += _copy_table(src, dst, table)
    # any extra tables in sqlite
    for table in inspect(src).get_table_names():
        if table not in _TABLE_ORDER:
            total += _copy_table(src, dst, table)

    print(f"Done. Restored ~{total} rows.", flush=True)
    with dst.connect() as c:
        for t in ("raw_posts", "processed_posts", "signals", "users", "omop_person"):
            if t in inspect(dst).get_table_names():
                print(f"  verify {t}={c.execute(text(f'select count(*) from {t}')).scalar()}", flush=True)


if __name__ == "__main__":
    main()
