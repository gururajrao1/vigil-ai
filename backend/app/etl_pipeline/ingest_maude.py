"""Bulk MAUDE (openFDA device/event) JSON → dashboard posts.

Reads unzipped partition JSON from ``download_openfda`` layout::

    <out-dir>/device/event/*.json

Each file matches live ``/device/event`` shape. Converts MDRs to ``raw_posts``
with ``platform=maude`` / ``external_id=maude_{report_number}`` (aligned with
``crawl_maude_live``).

Usage::

    python -m app.etl_pipeline.ingest_maude \\
      --maude-json C:/Users/Gururaja/Data/vigilai/openfda/device/event \\
      --batch-size 1000 --limit 50000 --recompute-signals
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from dotenv import load_dotenv

LOGGER = logging.getLogger("vigilai.etl.ingest_maude")

DEFAULT_BATCH = 1_000


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


def _iter_json_file_events(path: Path) -> Iterator[dict]:
    try:
        import ijson  # type: ignore
    except ImportError:
        ijson = None  # type: ignore

    if ijson is not None:
        with path.open("rb") as fh:
            try:
                for event in ijson.items(fh, "results.item"):
                    if isinstance(event, dict):
                        yield event
                return
            except Exception:
                fh.seek(0)
            try:
                for event in ijson.items(fh, "item"):
                    if isinstance(event, dict):
                        yield event
                return
            except Exception:
                fh.seek(0)

    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        results = raw.get("results") or []
    elif isinstance(raw, list):
        results = raw
    else:
        results = []
    for event in results:
        if isinstance(event, dict):
            yield event


def _batched(iterable, size: int):
    batch: List[dict] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _event_to_maude_post(event: dict) -> Optional[dict[str, Any]]:
    report_id = str(
        event.get("report_number") or event.get("mdr_report_key") or ""
    ).strip()
    if not report_id:
        report_id = hashlib.sha1(repr(event).encode("utf-8")).hexdigest()[:16]

    devices = event.get("device") or []
    if not isinstance(devices, list):
        devices = []
    brand = ""
    generic = ""
    for d in devices:
        if not isinstance(d, dict):
            continue
        brand = brand or (d.get("brand_name") or "").strip()
        generic = generic or (d.get("generic_name") or "").strip()
        openfda = d.get("openfda") or {}
        if not generic:
            names = openfda.get("device_name") or []
            if isinstance(names, list) and names:
                generic = str(names[0]).strip()
            elif isinstance(names, str):
                generic = names.strip()
    dev_name = brand or generic or "Unknown device"

    texts = event.get("mdr_text") or []
    if not isinstance(texts, list):
        texts = []
    narratives = [
        t.get("text", "")
        for t in texts
        if isinstance(t, dict)
        and t.get("text_type_code") in ("2500", "1000", "3000")
        and t.get("text")
    ]
    if not narratives:
        narratives = [
            t.get("text", "") for t in texts if isinstance(t, dict) and t.get("text")
        ]
    narrative = " ".join(str(n) for n in narratives)[:800]
    event_type = str(event.get("event_type") or "malfunction").strip().lower()
    date_str = str(event.get("date_received") or "")
    country = str(event.get("manufacturer_g1_country") or "").strip().upper()

    posted = datetime.utcnow()
    if date_str and len(date_str) == 8:
        try:
            posted = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            pass

    failure_cue = {
        "malfunction": "device malfunction and failure to operate",
        "injury": "patient injury adverse event from device malfunction",
        "death": "patient death adverse event associated with device failure",
    }.get(event_type, "device malfunction adverse event")
    alias = f"{brand} {generic}".strip()
    body = (
        f"FDA MAUDE adverse device report. Device product: {dev_name}. "
        f"{('Also known as: ' + alias + '. ') if alias and alias != dev_name else ''}"
        f"Reported event: {event_type} - {failure_cue}. "
        f"This was a serious negative patient experience. {narrative}"
    ).strip()

    try:
        from ..ingestion.sources import _country_to_region

        region = _country_to_region(country)
    except Exception:
        region = "North America" if country in {"", "US"} else "Global"

    return {
        "external_id": f"maude_{report_id}",
        "platform": "maude",
        "product_type": "device",
        "url": (
            "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/"
            f"detail.cfm?mdrfoi__id={report_id}"
        ),
        "author": f"maude:{report_id}",
        "title": f"MAUDE: {dev_name[:80]} -> {event_type}",
        "body": body,
        "region": region,
        "country": country or "US",
        "posted_at": posted,
    }


def _flush_maude_posts(
    posts: Sequence[dict[str, Any]],
    *,
    project_id: Optional[int],
    db_ready: bool = False,
) -> int:
    """Reuse FAERS bulk post writer (same RawPost / ProcessedPost shape)."""
    from .ingest_faers import _flush_posts_sync

    return _flush_posts_sync(posts, project_id=project_id, db_ready=db_ready)


def ingest_maude(
    *,
    maude_json: Optional[Path] = None,
    limit: int = 50_000,
    batch_size: int = DEFAULT_BATCH,
    project_id: Optional[int] = None,
    recompute_signals: bool = False,
) -> dict[str, Any]:
    load_dotenv()
    if not maude_json:
        raise ValueError("--maude-json file or directory is required")
    root = Path(maude_json)
    if not root.exists():
        raise FileNotFoundError(root)

    from ..database import SessionLocal, init_db
    from ..pipeline import recompute_signals as _recompute

    init_db()
    LOGGER.info("Sync schema ready for MAUDE->posts bridge")

    def _source() -> Iterator[dict]:
        if root.is_file():
            yield from _iter_json_file_events(root)
            return
        for fp in sorted(root.glob("*.json")):
            yield from _iter_json_file_events(fp)

    totals = {"posts": 0, "dropped": 0, "batches": 0, "events_processed": 0}
    processed = 0
    for batch in _batched(_source(), batch_size):
        if processed >= limit:
            break
        if processed + len(batch) > limit:
            batch = batch[: max(0, limit - processed)]
        post_dicts: List[dict[str, Any]] = []
        for event in batch:
            post = _event_to_maude_post(event)
            if post is None:
                totals["dropped"] += 1
                continue
            if project_id is not None:
                post["project_id"] = project_id
            post_dicts.append(post)
        n = _flush_maude_posts(post_dicts, project_id=project_id, db_ready=True)
        totals["posts"] += n
        totals["batches"] += 1
        processed += len(batch)
        totals["events_processed"] = processed
        LOGGER.info(
            "Batch %d — events=%d posts+%d dropped=%d",
            totals["batches"],
            len(batch),
            n,
            totals["dropped"],
        )

    if recompute_signals and totals["posts"] > 0:
        db = SessionLocal()
        try:
            sig = _recompute(db, project_id=project_id)
            totals["signals_recomputed"] = sig
            LOGGER.info("recompute_signals after MAUDE posts: %s", sig)
        finally:
            db.close()

    return {"mode": "maude_json", "batch_size": batch_size, "limit": limit, **totals}


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest openFDA device/event (MAUDE) JSON partitions into posts"
    )
    parser.add_argument("--maude-json", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--recompute-signals", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)
    try:
        result = ingest_maude(
            maude_json=args.maude_json,
            limit=args.limit,
            batch_size=args.batch_size,
            project_id=args.project_id,
            recompute_signals=args.recompute_signals,
        )
        LOGGER.info("MAUDE ingest complete: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("ingest_maude failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
