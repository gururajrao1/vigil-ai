"""Real background monitoring worker with self-healing crawl logic.

Self-healing means:
  1. Each source is tried up to MAX_RETRIES times with exponential back-off.
  2. If a source fails all retries it is quarantined for QUARANTINE_SECONDS
     before being re-admitted — the worker transparently switches to the next
     healthy source in the fallback chain for that tick.
  3. A per-source health registry tracks consecutive failures, last success,
     and quarantine expiry so the status endpoint gives full visibility.
  4. The fallback chain for each mode is: primary → secondary → synthetic
     (synthetic always works offline, so the worker never goes fully dark).
  5. All healing decisions are logged to last_error with timestamps so you
     can see exactly what switched and why.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from .database import SessionLocal
from .ingestion.synthetic import stream_batch
from .pipeline import ingest_posts, recompute_signals

MAX_RETRIES = 2           # attempts before quarantining a source
RETRY_DELAY = 4.0         # seconds between retries (doubles each attempt)
QUARANTINE_SECONDS = 300  # 5 minutes before a failed source is re-tried


# --------------------------------------------------------------------------- #
# Source registry — ordered fallback chains per mode
# --------------------------------------------------------------------------- #
def _make_source_fn(mode: str, query: str) -> Callable:
    """Return the crawl callable for a given mode + query."""
    q = query or "drug side effect adverse reaction"
    if mode == "twitter":
        from .ingestion.sources import crawl_twitter
        return lambda: ({"posts": crawl_twitter(q, 25), "unique_fetched": 25})
    if mode == "reddit":
        from .ingestion.sources import crawl_reddit_rss
        return lambda: ({"posts": crawl_reddit_rss(q, 15), "unique_fetched": 15})
    if mode == "reddit_health":
        from .ingestion.sources import crawl_reddit_health
        return lambda: crawl_reddit_health(q, 50)
    if mode == "reddit_pullpush":
        from .ingestion.sources import crawl_reddit_pullpush
        return lambda: crawl_reddit_pullpush(q, 40)
    if mode == "google_news":
        from .ingestion.sources import crawl_google_news
        return lambda: crawl_google_news(q if q != "drug side effect adverse reaction" else None, 25)
    if mode == "faers_live":
        from .ingestion.sources import crawl_faers
        return lambda: crawl_faers(limit=25, days_back=90)
    if mode == "dailymed_rss":
        from .ingestion.sources import crawl_dailymed_rss
        return lambda: crawl_dailymed_rss(limit=40)
    if mode == "pubmed_live":
        from .ingestion.sources import crawl_pubmed_live
        return lambda: crawl_pubmed_live(q, limit=20)
    if mode == "fda_rss":
        from .ingestion.sources import crawl_fda_all
        return lambda: crawl_fda_all(limit=40)
    if mode == "mhra_devices":
        from .ingestion.sources import crawl_mhra_devices
        return lambda: crawl_mhra_devices(limit=40)
    if mode == "hackernews":
        from .ingestion.sources import crawl_hackernews
        return lambda: crawl_hackernews(q, limit=30)
    if mode == "life_science":
        from .ingestion.sources import crawl_life_science_news
        # query doubles as optional feed_id (e.g. "stat", "sciencedaily")
        feed = q if q and q not in (
            "drug side effect adverse reaction", "drug side effect OR adverse drug reaction"
        ) else None
        return lambda: crawl_life_science_news(feed_id=feed, limit=40)
    if mode == "youtube":
        from .ingestion.sources import crawl_youtube
        return lambda: crawl_youtube(q, limit=20)
    if mode == "maude_live":
        from .ingestion.sources import crawl_maude_live
        return lambda: crawl_maude_live(limit=25, days_back=60)
    if mode == "device_news":
        from .ingestion.sources import crawl_device_news
        return lambda: crawl_device_news(limit=30)
    if mode == "device_recalls":
        from .ingestion.sources import crawl_device_recalls
        return lambda: crawl_device_recalls(limit=25)
    # default / stream / unknown
    return lambda: {"posts": stream_batch(3, seed=int(time.time())), "unique_fetched": 3}


# Fallback chains: if primary fails, try each fallback in order.
# Last entry is always "stream" (synthetic, never fails).
_FALLBACK_CHAINS: Dict[str, List[str]] = {
    "twitter":       ["twitter",       "reddit_pullpush", "google_news", "stream"],
    "reddit":        ["reddit",        "reddit_pullpush", "google_news", "stream"],
    "reddit_health": ["reddit_health", "reddit_pullpush", "google_news", "stream"],
    "reddit_pullpush":["reddit_pullpush","google_news",   "stream"],
    "google_news":   ["google_news",   "fda_rss",         "stream"],
    "faers_live":    ["faers_live",    "fda_rss",          "google_news", "stream"],
    "dailymed_rss":  ["dailymed_rss",  "pubmed_live",     "google_news", "stream"],
    "pubmed_live":   ["pubmed_live",   "google_news",     "stream"],
    "fda_rss":       ["fda_rss",       "google_news",     "stream"],
    "mhra_devices":  ["mhra_devices",  "fda_rss",         "google_news", "stream"],
    "maude_live":    ["maude_live",    "device_recalls",  "device_news", "stream"],
    "device_news":   ["device_news",   "device_recalls",  "maude_live", "stream"],
    "device_recalls":["device_recalls","maude_live",      "device_news", "stream"],
    "hackernews":    ["hackernews",    "google_news",     "stream"],
    "life_science":  ["life_science",  "google_news",     "stream"],
    "youtube":       ["youtube",       "google_news",     "stream"],
    "stream":        ["stream"],
}


class SourceHealth:
    """Tracks health metrics for a single source."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self.consecutive_failures: int = 0
        self.total_failures: int = 0
        self.total_successes: int = 0
        self.last_success: Optional[str] = None
        self.last_failure: Optional[str] = None
        self.last_error_msg: Optional[str] = None
        self.quarantine_until: Optional[float] = None  # epoch seconds

    def is_quarantined(self) -> bool:
        if self.quarantine_until is None:
            return False
        if time.time() < self.quarantine_until:
            return True
        # quarantine expired — reset
        self.quarantine_until = None
        self.consecutive_failures = 0
        return False

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.total_successes += 1
        self.last_success = datetime.utcnow().isoformat()
        self.quarantine_until = None

    def record_failure(self, error: str) -> None:
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure = datetime.utcnow().isoformat()
        self.last_error_msg = error
        if self.consecutive_failures >= MAX_RETRIES:
            self.quarantine_until = time.time() + QUARANTINE_SECONDS

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "healthy": not self.is_quarantined() and self.consecutive_failures < MAX_RETRIES,
            "quarantined": self.is_quarantined(),
            "quarantine_until": (
                datetime.utcfromtimestamp(self.quarantine_until).isoformat()
                if self.quarantine_until else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_error": self.last_error_msg,
        }


class MonitorScheduler:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.interval = 30
        self.mode = "stream"
        self.query = "drug side effects"
        self.ticks = 0
        self.last_run: Optional[str] = None
        self.last_ingested = 0
        self.last_error: Optional[str] = None
        self.last_source_used: Optional[str] = None  # may differ from mode if healed
        self.session_id: Optional[str] = None
        self.total_posts_ingested: int = 0
        self.batches_processed: int = 0
        self.started_at: Optional[str] = None
        self.latest_batch_at: Optional[str] = None
        # Per-source health registry (populated lazily)
        self._health: Dict[str, SourceHealth] = {}

    def _source_health(self, sid: str) -> SourceHealth:
        if sid not in self._health:
            self._health[sid] = SourceHealth(sid)
        return self._health[sid]

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "interval_seconds": self.interval,
            "mode": self.mode,
            "last_source_used": self.last_source_used,
            "ticks": self.ticks,
            "last_run": self.last_run,
            "last_ingested": self.last_ingested,
            "last_error": self.last_error,
            "session_id": self.session_id,
            "total_posts_ingested": self.total_posts_ingested,
            "batches_processed": self.batches_processed,
            "started_at": self.started_at,
            "latest_batch_at": self.latest_batch_at,
            "source_health": {sid: h.to_dict() for sid, h in self._health.items()},
        }

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, interval: int = 30, mode: str = "stream",
              query: str = "drug side effects") -> dict:
        with self._lock:
            if self.is_running():
                return self.status()
            self.interval = max(5, int(interval))
            self.mode = mode
            self.query = query
            self._stop.clear()
            self.session_id = str(uuid.uuid4())
            self.batches_processed = 0
            self.started_at = datetime.utcnow().isoformat()
            self.latest_batch_at = None
            self._thread = threading.Thread(
                target=self._run, name="vigilai-monitor", daemon=True
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        return self.status()

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            self._tick()
            if self._stop.wait(self.interval):
                break

    def _try_source(self, source_id: str, db) -> Tuple[int, bool]:
        """Attempt to crawl ``source_id`` with retries. Returns (new_posts, success)."""
        health = self._source_health(source_id)
        if health.is_quarantined():
            return 0, False

        fn = _make_source_fn(source_id, self.query)
        last_exc: str = ""
        delay = RETRY_DELAY

        for attempt in range(MAX_RETRIES):
            try:
                batch = fn()
                # crawl_twitter returns a list directly
                posts = batch if isinstance(batch, list) else batch.get("posts", [])
                fast = source_id not in ("twitter", "reddit", "reddit_health",
                                         "reddit_pullpush")
                new = ingest_posts(
                    db, posts,
                    use_transformer=not fast,
                    use_presidio=not fast,
                    online_translation=not fast,
                )
                health.record_success()
                return new, True
            except Exception as exc:
                last_exc = str(exc)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2  # exponential back-off

        health.record_failure(last_exc)
        return 0, False

    def _tick(self) -> None:
        db = SessionLocal()
        try:
            chain = _FALLBACK_CHAINS.get(self.mode, [self.mode, "stream"])
            new = 0
            used_source = self.mode

            for source_id in chain:
                new, ok = self._try_source(source_id, db)
                if ok:
                    used_source = source_id
                    if source_id != self.mode:
                        self.last_error = (
                            f"[self-heal] primary '{self.mode}' unavailable — "
                            f"used fallback '{source_id}' at "
                            f"{datetime.utcnow().strftime('%H:%M:%S UTC')}"
                        )
                    else:
                        self.last_error = None
                    break
            else:
                # All sources in chain failed (shouldn't happen — stream is always last)
                self.last_error = f"All sources in chain {chain} failed — no posts ingested"

            recompute_signals(db, use_fda=False, with_narrative=False)
            self.ticks += 1
            self.total_posts_ingested += new
            self.batches_processed += 1
            self.last_ingested = new
            self.last_source_used = used_source
            self.last_run = datetime.utcnow().isoformat()
            self.latest_batch_at = self.last_run

        except Exception as exc:
            self.last_error = str(exc)
        finally:
            db.close()


scheduler = MonitorScheduler()
