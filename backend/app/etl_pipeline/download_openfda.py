"""Download openFDA bulk JSON partitions (drug FAERS + device MAUDE).

Master index (no API key)::

    https://api.fda.gov/download.json

Paths used:

* ``results.drug.event.partitions[]``  — FAERS ICSRs (~1.7k zip parts)
* ``results.device.event.partitions[]`` — MAUDE MDRs (~365 parts)

Each partition is a JSON file (sometimes ``.json.zip``) with the same shape as
live ``/drug/event`` or ``/device/event`` query results (``{meta, results:[…]}``).

CLI::

    python -m app.etl_pipeline.download_openfda --domain both \\
        --out-dir C:/Users/Gururaja/Data/vigilai/openfda --workers 4

API::

    GET  /api/etl/openfda/partitions?domain=both
    POST /api/etl/openfda/download  {domain, out_dir, limit, workers, skip_existing}
"""
from __future__ import annotations

import argparse
import concurrent.futures
import logging
import os
import sys
import zipfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, List, Literal, Optional, Sequence
from urllib.parse import urlparse

LOGGER = logging.getLogger("vigilai.etl.download_openfda")

DOWNLOAD_INDEX_URL = "https://api.fda.gov/download.json"
USER_AGENT = "VigilAI-ETL/2.0 (openFDA bulk download; offline-first PV)"

Domain = Literal["drug", "device", "both"]

_DOMAIN_PATHS = {
    "drug": ("drug", "event"),
    "device": ("device", "event"),
}


@dataclass(frozen=True)
class PartitionInfo:
    domain: str  # drug | device
    endpoint: str  # event
    display_name: str
    file_url: str
    records: int
    size_mb: float
    index: int

    @property
    def suggested_filename(self) -> str:
        name = Path(urlparse(self.file_url).path).name
        if name.endswith(".zip"):
            name = name[: -len(".zip")]
        if not name.endswith(".json"):
            name = f"{name}.json"
        # Prefix domain so drug/device never collide in a shared folder
        if not name.startswith(f"{self.domain}-") and not name.startswith(
            ("drug-event", "device-event")
        ):
            name = f"{self.domain}-{name}"
        return name


def _http_get(url: str, *, timeout: float = 120.0) -> bytes:
    import httpx

    headers = {"User-Agent": USER_AGENT}
    # Optional openFDA key raises rate limits for the index / downloads when set
    try:
        from ..config import settings

        key = (getattr(settings, "openfda_api_key", None) or "").strip()
        if key and "api.fda.gov" in url:
            # download.open.fda.gov hosts usually ignore api_key; index accepts it
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}api_key={key}"
    except Exception:
        pass

    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def fetch_download_index(timeout: float = 120.0) -> dict[str, Any]:
    """Return the parsed ``download.json`` catalog."""
    raw = _http_get(DOWNLOAD_INDEX_URL, timeout=timeout)
    import json

    return json.loads(raw.decode("utf-8"))


def list_partitions(
    domain: Domain = "both",
    *,
    index: Optional[dict[str, Any]] = None,
) -> List[PartitionInfo]:
    """Flatten drug and/or device event partitions from the openFDA catalog."""
    catalog = index or fetch_download_index()
    results = catalog.get("results") or {}
    domains: Sequence[str]
    if domain == "both":
        domains = ("drug", "device")
    else:
        domains = (domain,)

    out: List[PartitionInfo] = []
    for dom in domains:
        noun, ep = _DOMAIN_PATHS[dom]
        block = (results.get(noun) or {}).get(ep) or {}
        parts = block.get("partitions") or []
        for i, part in enumerate(parts):
            url = str(part.get("file") or "").strip()
            if not url:
                continue
            # Prefer https
            if url.startswith("http://"):
                url = "https://" + url[len("http://") :]
            try:
                records = int(part.get("records") or 0)
            except (TypeError, ValueError):
                records = 0
            try:
                size_mb = float(part.get("size_mb") or 0.0)
            except (TypeError, ValueError):
                size_mb = 0.0
            out.append(
                PartitionInfo(
                    domain=dom,
                    endpoint=ep,
                    display_name=str(part.get("display_name") or f"{dom}-{i}"),
                    file_url=url,
                    records=records,
                    size_mb=size_mb,
                    index=i,
                )
            )
    return out


def summarize_partitions(parts: Sequence[PartitionInfo]) -> dict[str, Any]:
    by_domain: dict[str, dict[str, Any]] = {}
    for p in parts:
        bucket = by_domain.setdefault(
            p.domain, {"partitions": 0, "records": 0, "size_mb": 0.0}
        )
        bucket["partitions"] += 1
        bucket["records"] += p.records
        bucket["size_mb"] += p.size_mb
    return {
        "index_url": DOWNLOAD_INDEX_URL,
        "partition_count": len(parts),
        "by_domain": by_domain,
        "partitions": [asdict(p) for p in parts],
    }


def _extract_json_bytes(payload: bytes, url: str) -> bytes:
    """Return JSON bytes; unzip if the payload (or URL) is a zip archive."""
    looks_zip = url.rstrip("/").lower().endswith(".zip") or payload[:2] == b"PK"
    if not looks_zip:
        return payload
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".json")]
        if not names:
            names = list(zf.namelist())
        if not names:
            raise ValueError(f"Empty zip archive from {url}")
        # Prefer the largest JSON member (partition body)
        names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
        return zf.read(names[0])


def download_partition(
    part: PartitionInfo,
    out_dir: Path,
    *,
    skip_existing: bool = True,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Download one partition into ``out_dir/<domain>/`` as ``.json``."""
    dest_dir = out_dir / part.domain / "event"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / part.suggested_filename
    if skip_existing and dest.exists() and dest.stat().st_size > 0:
        return {
            "ok": True,
            "skipped": True,
            "path": str(dest),
            "domain": part.domain,
            "records": part.records,
            "display_name": part.display_name,
        }

    payload = _http_get(part.file_url, timeout=timeout)
    json_bytes = _extract_json_bytes(payload, part.file_url)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    tmp.write_bytes(json_bytes)
    tmp.replace(dest)
    return {
        "ok": True,
        "skipped": False,
        "path": str(dest),
        "domain": part.domain,
        "bytes": len(json_bytes),
        "records": part.records,
        "display_name": part.display_name,
    }


def download_partitions(
    *,
    domain: Domain = "both",
    out_dir: Path | str,
    limit: Optional[int] = None,
    workers: int = 4,
    skip_existing: bool = True,
    offset: int = 0,
) -> dict[str, Any]:
    """Download many partitions concurrently. ``limit`` caps how many files."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    parts = list_partitions(domain)
    if offset:
        parts = parts[offset:]
    if limit is not None and limit >= 0:
        parts = parts[:limit]

    results: List[dict[str, Any]] = []
    errors: List[dict[str, Any]] = []
    workers = max(1, min(int(workers or 1), 16))

    def _one(p: PartitionInfo) -> dict[str, Any]:
        try:
            return download_partition(p, out_path, skip_existing=skip_existing)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Download failed %s: %s", p.file_url, exc)
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "url": p.file_url,
                "domain": p.domain,
                "display_name": p.display_name,
            }

    if workers == 1:
        for p in parts:
            row = _one(p)
            (results if row.get("ok") else errors).append(row)
            if len(results) % 25 == 0 and results:
                LOGGER.info("Downloaded/skipped %d / %d", len(results), len(parts))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_one, p): p for p in parts}
            done = 0
            for fut in concurrent.futures.as_completed(futs):
                row = fut.result()
                (results if row.get("ok") else errors).append(row)
                done += 1
                if done % 25 == 0:
                    LOGGER.info("Progress %d / %d (ok=%d err=%d)", done, len(parts), len(results), len(errors))

    skipped = sum(1 for r in results if r.get("skipped"))
    written = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
    return {
        "ok": len(errors) == 0,
        "domain": domain,
        "out_dir": str(out_path.resolve()),
        "requested": len(parts),
        "written": written,
        "skipped_existing": skipped,
        "failed": len(errors),
        "errors": errors[:50],
        "layout": {
            "drug": str((out_path / "drug" / "event").resolve()),
            "device": str((out_path / "device" / "event").resolve()),
        },
    }


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
        description="Download openFDA drug (FAERS) + device (MAUDE) JSON partitions"
    )
    parser.add_argument(
        "--domain",
        choices=("drug", "device", "both"),
        default="both",
        help="Which openFDA event endpoint(s) to fetch",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(os.getenv("VIGILAI_OPENFDA_DIR") or "data/openfda"),
        help="Root folder; writes drug/event/*.json and device/event/*.json",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max partitions to download")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N partitions")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print partition summary from download.json and exit (no download)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    _configure_logging(args.verbose)

    try:
        parts = list_partitions(args.domain)
        summary = summarize_partitions(parts)
        LOGGER.info(
            "openFDA catalog — %d partitions (drug=%s device=%s)",
            summary["partition_count"],
            summary["by_domain"].get("drug"),
            summary["by_domain"].get("device"),
        )
        if args.list_only:
            # Compact stdout for scripting
            import json

            slim = {
                "index_url": summary["index_url"],
                "partition_count": summary["partition_count"],
                "by_domain": summary["by_domain"],
                "first": summary["partitions"][:3],
                "last": summary["partitions"][-3:],
            }
            print(json.dumps(slim, indent=2))
            return

        result = download_partitions(
            domain=args.domain,
            out_dir=args.out_dir,
            limit=args.limit,
            offset=args.offset,
            workers=args.workers,
            skip_existing=not args.no_skip_existing,
        )
        LOGGER.info("Download complete: %s", {k: result[k] for k in result if k != "errors"})
        if result["failed"]:
            LOGGER.error("%d failures (showing up to 50 in payload)", result["failed"])
            raise SystemExit(2)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("download_openfda failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
