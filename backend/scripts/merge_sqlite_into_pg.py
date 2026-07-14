"""Merge unique posts from local SQLite into Postgres (Railway) without wiping.

Keeps existing Railway rows. Adds raw_posts (+ processed_posts) from
backend/vigilai.db when neither external_id nor content_hash already exist.

Usage (from backend/):
  railway variables --service api --kv | findstr DATABASE_URL  (or set DATABASE_URL)
  .venv\\Scripts\\python.exe scripts\\merge_sqlite_into_pg.py

Does not print connection secrets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_BACKEND = Path(__file__).resolve().parents[1]
_SQLITE = _BACKEND / "vigilai.db"


def _pg_url() -> str:
    # Prefer public proxy when running from a laptop (internal DNS won't resolve).
    url = (
        os.getenv("DATABASE_PUBLIC_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    if not url.startswith("postgres"):
        raise SystemExit("Set DATABASE_PUBLIC_URL or DATABASE_URL first.")
    url = (
        url.replace("&channel_binding=require", "")
        .replace("?channel_binding=require&", "?")
        .replace("?channel_binding=require", "")
    )
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _rows(conn, sql: str, **params):
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def _coerce_bools(row: dict, bool_cols: set[str]) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, str):
            # Postgres text cannot contain NUL bytes (scraped junk).
            v = v.replace("\x00", "")
        if k in bool_cols:
            if v is None:
                out[k] = None
            elif isinstance(v, bool):
                out[k] = v
            else:
                out[k] = bool(int(v)) if str(v).isdigit() else bool(v)
        else:
            out[k] = v
    return out


def main() -> None:
    if not _SQLITE.is_file():
        raise SystemExit(f"SQLite not found: {_SQLITE}")

    pg = _pg_url()
    print(f"SQLite: {_SQLITE} ({_SQLITE.stat().st_size // 1024} KB)")
    print(f"Postgres host: {pg.split('@')[-1].split('/')[0]}")

    src = create_engine(f"sqlite:///{_SQLITE}", future=True)
    dst = create_engine(
        pg,
        future=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 30},
    )

    print("Connecting to Postgres…", flush=True)
    with src.connect() as sconn, dst.connect() as dconn:
        print("Connected.", flush=True)
        # Map project slug → ids on both sides
        src_proj = {
            r["slug"]: r["id"]
            for r in _rows(sconn, "SELECT id, slug FROM projects")
        }
        dst_proj = {
            r["slug"]: r["id"]
            for r in _rows(dconn, "SELECT id, slug FROM projects")
        }
        # SQLite project_id → Railway project_id
        proj_map: dict[int | None, int | None] = {None: dst_proj.get("general-pv")}
        for slug, sid in src_proj.items():
            proj_map[sid] = dst_proj.get(slug, dst_proj.get("general-pv"))

        existing_ext = {
            r[0]
            for r in dconn.execute(
                text("SELECT external_id FROM raw_posts WHERE external_id IS NOT NULL")
            ).fetchall()
            if r[0]
        }
        existing_hash = {
            r[0]
            for r in dconn.execute(
                text("SELECT content_hash FROM raw_posts WHERE content_hash IS NOT NULL")
            ).fetchall()
            if r[0]
        }

        insp_dst = inspect(dst)
        raw_cols = {c["name"] for c in insp_dst.get_columns("raw_posts")} - {"id"}
        proc_cols = {c["name"] for c in insp_dst.get_columns("processed_posts")} - {"id"}
        raw_bools = {
            c["name"]
            for c in insp_dst.get_columns("raw_posts")
            if "BOOL" in str(c["type"]).upper()
        }
        proc_bools = {
            c["name"]
            for c in insp_dst.get_columns("processed_posts")
            if "BOOL" in str(c["type"]).upper()
        }

        src_raw_cols = {c["name"] for c in inspect(src).get_columns("raw_posts")}
        raw_overlap = sorted(raw_cols & src_raw_cols)

        sqlite_raws = _rows(
            sconn,
            f"SELECT {', '.join(raw_overlap + ['id'])} FROM raw_posts ORDER BY id",
        )
        # processed by raw_id
        src_proc_cols = {c["name"] for c in inspect(src).get_columns("processed_posts")}
        proc_overlap = sorted((proc_cols & src_proc_cols) | {"raw_id"})
        procs = {
            r["raw_id"]: r
            for r in _rows(
                sconn,
                f"SELECT {', '.join(proc_overlap)} FROM processed_posts",
            )
        }

        print(f"SQLite raw_posts: {len(sqlite_raws)}")
        print(f"Railway existing: ext={len(existing_ext)} hash={len(existing_hash)}")

        added = 0
        skipped = 0
        no_proc = 0

        try:
            for raw in sqlite_raws:
                old_id = raw.pop("id")
                ext = raw.get("external_id")
                ch = raw.get("content_hash")
                if (ext and ext in existing_ext) or (ch and ch in existing_hash):
                    skipped += 1
                    continue

                raw["project_id"] = proj_map.get(raw.get("project_id"), dst_proj.get("general-pv"))
                payload = _coerce_bools({k: raw[k] for k in raw_overlap if k in raw}, raw_bools)
                col_list = ", ".join(payload.keys())
                placeholders = ", ".join(f":{k}" for k in payload.keys())

                new_id = dconn.execute(
                    text(
                        f"INSERT INTO raw_posts ({col_list}) VALUES ({placeholders}) "
                        f"RETURNING id"
                    ),
                    payload,
                ).scalar_one()

                proc = procs.get(old_id)
                if proc:
                    p = dict(proc)
                    p.pop("raw_id", None)
                    p.pop("id", None)
                    p["raw_id"] = new_id
                    p = _coerce_bools(
                        {k: p[k] for k in proc_cols if k in p},
                        proc_bools,
                    )
                    if "raw_id" not in p:
                        p["raw_id"] = new_id
                    pcols = ", ".join(p.keys())
                    pph = ", ".join(f":{k}" for k in p.keys())
                    dconn.execute(
                        text(f"INSERT INTO processed_posts ({pcols}) VALUES ({pph})"),
                        p,
                    )
                else:
                    no_proc += 1

                if ext:
                    existing_ext.add(ext)
                if ch:
                    existing_hash.add(ch)
                added += 1
                if added % 50 == 0:
                    dconn.commit()
                    print(f"  …added {added} (committed)", flush=True)

            for table in ("raw_posts", "processed_posts"):
                try:
                    dconn.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                        )
                    )
                except Exception:
                    pass

            dconn.commit()
        except Exception as exc:
            # Keep already-committed batches; only roll back the open batch.
            try:
                dconn.rollback()
            except Exception:
                pass
            print(f"Stopped early after added={added}: {exc}", flush=True)
            raise

        final = dconn.execute(text("SELECT COUNT(*) FROM raw_posts")).scalar_one()
        print(
            f"Done. added={added} skipped_dupes={skipped} missing_processed={no_proc} "
            f"railway_total={final}",
            flush=True,
        )


if __name__ == "__main__":
    main()
