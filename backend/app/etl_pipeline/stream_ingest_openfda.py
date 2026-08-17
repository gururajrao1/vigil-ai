"""Stream-ingest openFDA partition files directly from download URLs.

No full local mirror required: for each partition in
``https://api.fda.gov/download.json`` we HTTP-GET the zip/JSON, parse
``results[]`` with ``ijson``, and flush into VigilAI (FAERS → OMOP+posts,
MAUDE → posts).

CLI::

    python -m app.etl_pipeline.stream_ingest_openfda --domain both \\
        --max-partitions 10 --event-limit 50000 --recompute-signals

API::

    POST /api/etl/openfda/stream-ingest
    GET  /api/etl/openfda/stream-ingest/{job_id}
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Iterator, List, Literal, Optional, Sequence

from dotenv import load_dotenv

from .download_openfda import (
    PartitionInfo,
    _extract_json_bytes,
    _http_get,
    list_partitions,
)

LOGGER = logging.getLogger("vigilai.etl.stream_ingest_openfda")

DomainLiteral = Literal["drug", "device", "both"]

_JOBS: Dict[str, "StreamIngestJob"] = {}
_JOBS_LOCK = threading.Lock()


@dataclass
class StreamIngestJob:
    job_id: str
    domain: str
    status: str = "pending"  # pending|running|completed|failed|cancelled
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    max_partitions: Optional[int] = None
    offset: int = 0
    event_limit: Optional[int] = None
    batch_size: int = 500
    also_posts: bool = True
    also_omop: bool = True
    recompute_signals: bool = False
    project_id: Optional[int] = None
    partitions_total: int = 0
    partitions_done: int = 0
    events_seen: int = 0
    posts_inserted: int = 0
    omop_persons: int = 0
    omop_drugs: int = 0
    omop_conditions: int = 0
    dropped: int = 0
    current_partition: Optional[str] = None
    error: Optional[str] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_job(job_id: str) -> Optional[StreamIngestJob]:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def list_jobs(limit: int = 20) -> List[dict[str, Any]]:
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda j: j.created_at, reverse=True)
    return [j.to_dict() for j in jobs[:limit]]


def _resolve_project_id(explicit: Optional[int]) -> Optional[int]:
    if explicit is not None:
        return explicit
    try:
        from ..database import SessionLocal, init_db
        from ..models import Project

        init_db()
        db = SessionLocal()
        try:
            row = db.query(Project).filter(Project.slug == "general-pv").first()
            if row is None:
                row = db.query(Project).order_by(Project.id.asc()).first()
            return int(row.id) if row is not None else None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Could not resolve default project_id: %s", exc)
        return None


def _iter_events_from_bytes(payload: bytes, url: str) -> Iterator[dict]:
    json_bytes = _extract_json_bytes(payload, url)
    try:
        import ijson  # type: ignore
    except ImportError:
        ijson = None  # type: ignore

    if ijson is not None:
        bio = BytesIO(json_bytes)
        try:
            for event in ijson.items(bio, "results.item"):
                if isinstance(event, dict):
                    yield event
            return
        except Exception:
            bio.seek(0)
        try:
            for event in ijson.items(bio, "item"):
                if isinstance(event, dict):
                    yield event
            return
        except Exception:
            pass

    import json

    raw = json.loads(json_bytes.decode("utf-8"))
    if isinstance(raw, dict):
        results = raw.get("results") or []
    elif isinstance(raw, list):
        results = raw
    else:
        results = []
    for event in results:
        if isinstance(event, dict):
            yield event


def _fetch_partition_events(part: PartitionInfo) -> Iterator[dict]:
    LOGGER.info(
        "Fetching %s (%s, ~%s records)", part.display_name, part.domain, part.records
    )
    payload = _http_get(part.file_url, timeout=300.0)
    yield from _iter_events_from_bytes(payload, part.file_url)


def _batched(events: Sequence[dict], size: int) -> Iterator[List[dict]]:
    for i in range(0, len(events), size):
        yield list(events[i : i + size])


async def _run_stream_async(
    *,
    domain: DomainLiteral,
    parts: List[PartitionInfo],
    event_limit: Optional[int],
    batch_size: int,
    also_posts: bool,
    also_omop: bool,
    recompute_signals: bool,
    project_id: Optional[int],
    job: Optional[StreamIngestJob],
) -> dict[str, Any]:
    from ..db.pg_url import create_async_engine_normalized
    from .ingest_faers import (
        ConceptResolver,
        _ensure_schema,
        _event_to_faers_post,
        _flush_batch,
        _flush_posts_sync,
        _transform_event,
    )
    from .ingest_maude import _event_to_maude_post

    raw_url = (os.getenv("DATABASE_URL") or "").strip()
    if not raw_url:
        raise EnvironmentError("DATABASE_URL is required for openFDA stream ingest")

    need_omop = also_omop and any(p.domain == "drug" for p in parts)
    engine = None
    resolver = None
    if need_omop:
        engine = create_async_engine_normalized(raw_url)
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await _ensure_schema(conn)
        resolver = ConceptResolver()
        async with engine.begin() as conn:
            await resolver.load(conn)

    if also_posts:
        from ..database import init_db

        await asyncio.to_thread(init_db)

    events_budget = event_limit if event_limit is not None else 10**12
    events_seen = 0
    posts_inserted = 0
    omop_persons = omop_drugs = omop_conditions = dropped = 0
    partitions_done = 0

    try:
        for part in parts:
            if job and job.status == "cancelled":
                break
            if events_seen >= events_budget:
                break
            if job:
                job.current_partition = part.display_name

            remaining = events_budget - events_seen
            try:
                part_events = await asyncio.to_thread(
                    _fetch_partition_capped, part, remaining
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Partition fetch failed %s: %s", part.display_name, exc)
                if job:
                    job.message = f"Skip failed partition: {part.display_name}: {exc}"
                continue

            for batch in _batched(part_events, batch_size):
                if events_seen >= events_budget:
                    break
                if events_seen + len(batch) > events_budget:
                    batch = batch[: max(0, events_budget - events_seen)]

                if part.domain == "drug":
                    post_dicts: List[dict] = []
                    transformed: List[dict] = []
                    for event in batch:
                        if need_omop and resolver is not None:
                            row = _transform_event(event, resolver, project_id=project_id)
                            if row is None:
                                dropped += 1
                            else:
                                transformed.append(row)
                        if also_posts:
                            post = _event_to_faers_post(event)
                            if post is not None:
                                if project_id is not None:
                                    post["project_id"] = project_id
                                post_dicts.append(post)

                    if transformed and engine is not None:
                        async with engine.begin() as conn:
                            stats = await _flush_batch(conn, transformed)
                        omop_persons += int(stats.get("persons") or 0)
                        omop_drugs += int(stats.get("drugs") or 0)
                        omop_conditions += int(stats.get("conditions") or 0)

                    if post_dicts:
                        n = await asyncio.to_thread(
                            _flush_posts_sync,
                            post_dicts,
                            project_id=project_id,
                            db_ready=True,
                        )
                        posts_inserted += int(n or 0)
                else:
                    post_dicts = []
                    for event in batch:
                        post = _event_to_maude_post(event)
                        if post is None:
                            dropped += 1
                            continue
                        if project_id is not None:
                            post["project_id"] = project_id
                        post_dicts.append(post)
                    if post_dicts and also_posts:
                        n = await asyncio.to_thread(
                            _flush_posts_sync,
                            post_dicts,
                            project_id=project_id,
                            db_ready=True,
                        )
                        posts_inserted += int(n or 0)

                events_seen += len(batch)
                if job:
                    job.events_seen = events_seen
                    job.posts_inserted = posts_inserted
                    job.omop_persons = omop_persons
                    job.omop_drugs = omop_drugs
                    job.omop_conditions = omop_conditions
                    job.dropped = dropped

            partitions_done += 1
            if job:
                job.partitions_done = partitions_done
                job.message = (
                    f"Done {partitions_done}/{len(parts)} partitions; "
                    f"events={events_seen} posts+={posts_inserted}"
                )
            LOGGER.info(
                "Partition %d/%d %s — events_total=%d posts=%d",
                partitions_done,
                len(parts),
                part.display_name,
                events_seen,
                posts_inserted,
            )

        signals_info: Any = None
        if recompute_signals and posts_inserted > 0:
            from ..database import SessionLocal
            from ..pipeline import recompute_signals as _recompute

            def _recompute_sync() -> Any:
                db = SessionLocal()
                try:
                    return _recompute(db, project_id=project_id)
                finally:
                    db.close()

            signals_info = await asyncio.to_thread(_recompute_sync)
            LOGGER.info("recompute_signals: %s", signals_info)

        return {
            "ok": True,
            "domain": domain,
            "project_id": project_id,
            "partitions_total": len(parts),
            "partitions_done": partitions_done,
            "events_seen": events_seen,
            "posts_inserted": posts_inserted,
            "omop_persons": omop_persons,
            "omop_drugs": omop_drugs,
            "omop_conditions": omop_conditions,
            "dropped": dropped,
            "signals_recomputed": signals_info,
        }
    finally:
        if engine is not None:
            await engine.dispose()


def _take(it: Iterator[dict], n: int) -> Iterator[dict]:
    for i, item in enumerate(it):
        if i >= n:
            break
        yield item


def _fetch_partition_capped(part: PartitionInfo, n: int) -> List[dict]:
    """Fetch one partition and return at most ``n`` events (runs in a worker thread)."""
    return list(_take(_fetch_partition_events(part), n))


def stream_ingest_openfda(
    *,
    domain: DomainLiteral = "both",
    max_partitions: Optional[int] = None,
    offset: int = 0,
    event_limit: Optional[int] = None,
    batch_size: int = 500,
    also_posts: bool = True,
    also_omop: bool = True,
    recompute_signals: bool = False,
    project_id: Optional[int] = None,
    name_contains: Optional[str] = None,
    job: Optional[StreamIngestJob] = None,
) -> dict[str, Any]:
    load_dotenv()
    pid = _resolve_project_id(project_id)
    parts = list_partitions(domain)
    if name_contains:
        needle = name_contains.strip().lower()
        parts = [p for p in parts if needle in (p.display_name or "").lower()]
        LOGGER.info("Filtered to %s partition(s) matching %r", len(parts), name_contains)
    if offset:
        parts = parts[offset:]
    if max_partitions is not None:
        parts = parts[: max(0, max_partitions)]

    if job:
        job.status = "running"
        job.started_at = datetime.utcnow().isoformat() + "Z"
        job.partitions_total = len(parts)
        job.project_id = pid
        job.message = f"Streaming {len(parts)} partition(s)"

    try:
        result = asyncio.run(
            _run_stream_async(
                domain=domain,
                parts=parts,
                event_limit=event_limit,
                batch_size=batch_size,
                also_posts=also_posts,
                also_omop=also_omop,
                recompute_signals=recompute_signals,
                project_id=pid,
                job=job,
            )
        )
        if job:
            job.status = "cancelled" if job.status == "cancelled" else "completed"
            job.finished_at = datetime.utcnow().isoformat() + "Z"
            job.message = "Stream ingest finished"
            job.events_seen = int(result.get("events_seen") or 0)
            job.posts_inserted = int(result.get("posts_inserted") or 0)
            job.omop_persons = int(result.get("omop_persons") or 0)
            job.omop_drugs = int(result.get("omop_drugs") or 0)
            job.omop_conditions = int(result.get("omop_conditions") or 0)
            job.dropped = int(result.get("dropped") or 0)
            job.partitions_done = int(result.get("partitions_done") or 0)
        return result
    except Exception as exc:
        if job:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.utcnow().isoformat() + "Z"
        raise


def start_job(
    *,
    domain: DomainLiteral = "both",
    max_partitions: Optional[int] = 5,
    offset: int = 0,
    event_limit: Optional[int] = 50_000,
    batch_size: int = 500,
    also_posts: bool = True,
    also_omop: bool = True,
    recompute_signals: bool = True,
    project_id: Optional[int] = None,
) -> StreamIngestJob:
    job = StreamIngestJob(
        job_id=str(uuid.uuid4()),
        domain=domain,
        max_partitions=max_partitions,
        offset=offset,
        event_limit=event_limit,
        batch_size=batch_size,
        also_posts=also_posts,
        also_omop=also_omop,
        recompute_signals=recompute_signals,
        project_id=project_id,
    )
    with _JOBS_LOCK:
        _JOBS[job.job_id] = job

    def _run() -> None:
        try:
            stream_ingest_openfda(
                domain=domain,
                max_partitions=max_partitions,
                offset=offset,
                event_limit=event_limit,
                batch_size=batch_size,
                also_posts=also_posts,
                also_omop=also_omop,
                recompute_signals=recompute_signals,
                project_id=project_id,
                job=job,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("stream ingest job failed: %s", exc)
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.utcnow().isoformat() + "Z"

    threading.Thread(
        target=_run, name=f"openfda-stream-{job.job_id[:8]}", daemon=True
    ).start()
    return job


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


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Stream-ingest openFDA drug/device partitions from CDN URLs"
    )
    parser.add_argument("--domain", choices=("drug", "device", "both"), default="both")
    parser.add_argument(
        "--max-partitions",
        type=int,
        default=5,
        help="How many partition files to pull (default 5; use 0 for all ~2k)",
    )
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--name-contains",
        type=str,
        default=None,
        help="Only partitions whose display_name contains this (e.g. '2026 Q1')",
    )
    parser.add_argument(
        "--event-limit",
        type=int,
        default=50_000,
        help="Stop after this many events across partitions (0 = unlimited)",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--skip-posts", action="store_true")
    parser.add_argument("--skip-omop", action="store_true")
    parser.add_argument("--recompute-signals", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)

    max_p = None if args.max_partitions == 0 else args.max_partitions
    ev_lim = None if args.event_limit == 0 else args.event_limit
    try:
        result = stream_ingest_openfda(
            domain=args.domain,
            max_partitions=max_p,
            offset=args.offset,
            event_limit=ev_lim,
            batch_size=args.batch_size,
            also_posts=not args.skip_posts,
            also_omop=not args.skip_omop,
            recompute_signals=args.recompute_signals,
            project_id=args.project_id,
            name_contains=args.name_contains,
        )
        LOGGER.info("Stream ingest complete: %s", result)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("stream_ingest_openfda failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
