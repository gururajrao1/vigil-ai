"""Dump all public tables from current DATABASE_URL into a local SQLite file.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\dump_pg_to_sqlite.py --out data/vigilai_neon_backup.db
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


def _clean_pg(url: str) -> str:
    url = normalize_database_url((url or "").strip(), is_async=False)
    url = (
        url.replace("&channel_binding=require", "")
        .replace("?channel_binding=require&", "?")
        .replace("?channel_binding=require", "")
    )
    if "sslmode=" not in url and not url.startswith("sqlite"):
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _table_order(src: Engine) -> list[str]:
    names = set(inspect(src).get_table_names())
    preferred = [
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
    ordered = [t for t in preferred if t in names]
    for t in sorted(names):
        if t not in ordered and not t.startswith("sqlite_"):
            ordered.append(t)
    return ordered


def _copy_table(src: Engine, dst: Engine, table: str) -> int:
    insp_src = inspect(src)
    cols = [c["name"] for c in insp_src.get_columns(table)]
    if not cols:
        return 0
    col_list = ", ".join(f'"{c}"' for c in cols)
    with src.connect() as sconn:
        rows = sconn.execute(text(f"SELECT {col_list} FROM {table}")).mappings().all()
    if not rows:
        print(f"  {table}: 0", flush=True)
        return 0

    # Create table on SQLite from first-batch INSERT via SQLAlchemy reflection create
    # Simpler: use pandas-free raw CREATE from PG types loosely as TEXT/INTEGER/REAL/BLOB
    type_map = {}
    for c in insp_src.get_columns(table):
        tn = str(c["type"]).upper()
        if "INT" in tn or "SERIAL" in tn or "BOOL" in tn:
            type_map[c["name"]] = "INTEGER"
        elif any(x in tn for x in ("FLOAT", "DOUBLE", "NUMERIC", "REAL", "DECIMAL")):
            type_map[c["name"]] = "REAL"
        elif "TIMESTAMP" in tn or "DATE" in tn or "TIME" in tn:
            type_map[c["name"]] = "TEXT"
        else:
            type_map[c["name"]] = "TEXT"

    # SQLite needs INTEGER PRIMARY KEY for ORM autoincrement identity.
    pk_cols = {c["name"] for c in insp_src.get_pk_constraint(table).get("constrained_columns") or []}
    if not pk_cols and "id" in type_map:
        pk_cols = {"id"}
    ddl_parts = []
    for c in cols:
        decl = f'"{c}" {type_map[c]}'
        if c in pk_cols and type_map[c] == "INTEGER" and len(pk_cols) == 1:
            decl += " PRIMARY KEY"
        ddl_parts.append(decl)
    ddl_cols = ", ".join(ddl_parts)
    placeholders = ", ".join(f":{c}" for c in cols)
    with dst.begin() as dconn:
        dconn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
        dconn.execute(text(f'CREATE TABLE "{table}" ({ddl_cols})'))
        batch: list[dict] = []
        n = 0
        for row in rows:
            item = {}
            for c in cols:
                v = row[c]
                if isinstance(v, bool):
                    v = int(v)
                elif v is not None and not isinstance(v, (int, float, str, bytes)):
                    v = str(v)
                if isinstance(v, str):
                    v = v.replace("\x00", "")
                item[c] = v
            batch.append(item)
            if len(batch) >= 200:
                dconn.execute(
                    text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'),
                    batch,
                )
                n += len(batch)
                batch.clear()
        if batch:
            dconn.execute(
                text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'),
                batch,
            )
            n += len(batch)
    print(f"  {table}: {n}", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="data/vigilai_neon_backup.db",
        help="SQLite path relative to backend/",
    )
    ap.add_argument("--src-file", default="")
    ap.add_argument(
        "--tables",
        default="",
        help="Comma-separated table subset (faster). Empty = all tables.",
    )
    args = ap.parse_args()

    src_url = os.getenv("DATABASE_URL", "").strip()
    if args.src_file:
        src_url = Path(args.src_file).read_text(encoding="utf-8").strip()
    src_url = _clean_pg(src_url)

    out = Path(args.out)
    if not out.is_absolute():
        out = Path(__file__).resolve().parents[1] / out
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    print(f"Dumping to {out}", flush=True)
    src = create_engine(src_url, future=True, pool_pre_ping=True)
    dst = create_engine(f"sqlite:///{out.as_posix()}", future=True)

    wanted = {t.strip() for t in args.tables.split(",") if t.strip()} if args.tables else None
    tables = _table_order(src)
    if wanted is not None:
        tables = [t for t in tables if t in wanted]
        missing = wanted - set(tables)
        if missing:
            print(f"WARNING: tables not found: {sorted(missing)}", flush=True)

    total = 0
    for table in tables:
        total += _copy_table(src, dst, table)
    print(f"Done. ~{total} rows -> {out} ({out.stat().st_size // (1024*1024)} MB)", flush=True)


if __name__ == "__main__":
    main()
