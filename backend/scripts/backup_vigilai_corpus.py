"""Build a full VigilAI corpus backup pack (SQLite dump + inventory manifest).

Does not copy multi‑GB openFDA JSON into the repo — records paths + sizes + hashes
for external data under %USERPROFILE%/Data/vigilai when present.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from app.db.pg_url import normalize_database_url  # noqa: E402

_BACKEND = Path(__file__).resolve().parents[1]
_DEFAULT_DATA = Path(os.path.expandvars(r"%USERPROFILE%\Data\vigilai"))


def _sha256(path: Path, *, limit_mb: int = 64) -> str | None:
    """Hash file; skip content hash when larger than limit_mb (still record size)."""
    size = path.stat().st_size
    if size > limit_mb * 1024 * 1024:
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _inventory(root: Path) -> list[dict]:
    out: list[dict] = []
    if not root.exists():
        return out
    for fp in sorted(root.rglob("*")):
        if not fp.is_file():
            continue
        rel = str(fp.relative_to(root)).replace("\\", "/")
        info = {
            "path": str(fp),
            "rel": rel,
            "bytes": fp.stat().st_size,
            "mtime_utc": datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
        digest = _sha256(fp)
        if digest:
            info["sha256"] = digest
        else:
            info["sha256"] = None
            info["sha256_note"] = "skipped (>64MB); size recorded only"
        out.append(info)
    return out


def _db_counts(url: str) -> dict:
    eng = create_engine(url, pool_pre_ping=True)
    counts = {}
    with eng.connect() as c:
        for label, sql in (
            ("raw_posts", "SELECT COUNT(*) FROM raw_posts"),
            ("faers_posts", "SELECT COUNT(*) FROM raw_posts WHERE platform LIKE 'faers%'"),
            ("processed_posts", "SELECT COUNT(*) FROM processed_posts"),
            ("signals", "SELECT COUNT(*) FROM signals"),
            ("alerts", "SELECT COUNT(*) FROM alerts"),
            ("users", "SELECT COUNT(*) FROM users"),
            ("omop_person", "SELECT COUNT(*) FROM omop_person"),
            ("omop_drug_exposure", "SELECT COUNT(*) FROM omop_drug_exposure"),
            ("omop_condition_occurrence", "SELECT COUNT(*) FROM omop_condition_occurrence"),
        ):
            try:
                counts[label] = int(c.execute(text(sql)).scalar() or 0)
            except Exception as exc:
                counts[label] = f"error:{type(exc).__name__}"
    return counts


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _BACKEND / "data" / "backups" / f"vigilai_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_url = (os.environ.get("DATABASE_URL") or "").strip()
    host = "sqlite" if raw_url.startswith("sqlite") else raw_url.split("@")[-1].split("/")[0]
    print(f"Backup pack → {out_dir}", flush=True)
    print(f"DB host: {host}", flush=True)

    # 1) SQLite dump of live DB
    dump_path = out_dir / "vigilai_db.sqlite"
    from scripts.dump_pg_to_sqlite import main as dump_main  # type: ignore

    # call module as subprocess-equivalent
    import subprocess

    rc = subprocess.call(
        [
            sys.executable,
            str(_BACKEND / "scripts" / "dump_pg_to_sqlite.py"),
            "--out",
            str(dump_path),
        ],
        cwd=str(_BACKEND),
    )
    if rc != 0:
        raise SystemExit(f"dump_pg_to_sqlite failed rc={rc}")

    # 2) Copy prior neon backup if present
    prior = _BACKEND / "data" / "vigilai_neon_backup.db"
    if prior.exists():
        shutil.copy2(prior, out_dir / "vigilai_neon_backup_snapshot.db")
        print("copied prior neon snapshot", flush=True)

    # 3) External data inventory
    data_root = Path(os.environ.get("VIGILAI_DATA_ROOT") or _DEFAULT_DATA)
    inventory = _inventory(data_root)

    pg_url = normalize_database_url(raw_url, is_async=False) if raw_url.startswith("postgres") else raw_url
    counts = _db_counts(pg_url) if raw_url.startswith("postgres") else {}

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "database_host": host,
        "database_counts": counts,
        "sqlite_dump": str(dump_path.name),
        "sqlite_bytes": dump_path.stat().st_size if dump_path.exists() else 0,
        "external_data_root": str(data_root),
        "external_files": inventory,
        "notes": [
            "Multi-GB openFDA JSON files are inventoried by path/size only (not copied).",
            "Restore DB with: python scripts/restore_sqlite_to_pg.py --sqlite <vigilai_db.sqlite>",
            "Keep this folder offline for client demos; do not commit to git.",
        ],
    }
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"manifest → {man_path}", flush=True)
    print(f"db_counts {counts}", flush=True)
    print(f"external_files {len(inventory)}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
