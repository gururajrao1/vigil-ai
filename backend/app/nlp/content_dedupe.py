"""Semantic content hashing — drop cross-platform / syndicated duplicate posts.

Identical clinical narratives scraped under different ``external_id`` / platform
tags used to inflate PRR, ROR, and MaxSPRT. This module normalizes raw text,
hashes it, and gates duplicates before the 4-gate NLP path runs.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional, Set

logger = logging.getLogger("vigilai.content_dedupe")

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Process-wide telemetry (last + cumulative) for /api/nlp/resolver-status
_lock = threading.Lock()
_TELEMETRY: dict[str, Any] = {
    "total_scraped_records": 0,
    "suppressed_duplicate_records": 0,
    "clean_committed_records": 0,
    "last_batch": {
        "total_scraped_records": 0,
        "suppressed_duplicate_records": 0,
        "clean_committed_records": 0,
    },
}


def normalize_content(text: str) -> str:
    """Strip punctuation, fold case, compress whitespace → uniform baseline."""
    if not text:
        return ""
    folded = text.casefold()
    stripped = _PUNCT_RE.sub(" ", folded)
    return _SPACE_RE.sub(" ", stripped).strip()


def content_signature(*parts: str, algo: str = "sha256") -> str:
    """Hex digest of normalized concatenated narrative parts."""
    joined = " ".join(normalize_content(p or "") for p in parts)
    joined = _SPACE_RE.sub(" ", joined).strip()
    if not joined:
        return ""
    h = hashlib.new(algo if algo in hashlib.algorithms_available else "sha256")
    h.update(joined.encode("utf-8"))
    return h.hexdigest()


def post_content_signature(post: dict) -> str:
    """Signature for an ingest dict — title + body (clinical narrative)."""
    return content_signature(post.get("title") or "", post.get("body") or "")


def get_dedupe_telemetry() -> dict[str, Any]:
    with _lock:
        return {
            "total_scraped_records": _TELEMETRY["total_scraped_records"],
            "suppressed_duplicate_records": _TELEMETRY["suppressed_duplicate_records"],
            "clean_committed_records": _TELEMETRY["clean_committed_records"],
            "last_batch": dict(_TELEMETRY["last_batch"]),
        }


def _bump_telemetry(*, scraped: int, suppressed: int, committed: int) -> None:
    with _lock:
        _TELEMETRY["total_scraped_records"] += scraped
        _TELEMETRY["suppressed_duplicate_records"] += suppressed
        _TELEMETRY["clean_committed_records"] += committed
        _TELEMETRY["last_batch"] = {
            "total_scraped_records": scraped,
            "suppressed_duplicate_records": suppressed,
            "clean_committed_records": committed,
        }


@dataclass
class ContentDedupeGate:
    """High-velocity in-batch signature cache + optional DB master lookup.

    Gate rule: if signature already seen in this batch **or** already stored on
    a RawPost for the project, classify as structural duplicate and drop before NLP.
    """

    project_id: Optional[int] = None
    seen: Set[str] = field(default_factory=set)
    # sig → master raw_post id (first commit in batch / DB)
    masters: dict[str, int] = field(default_factory=dict)
    scraped: int = 0
    suppressed: int = 0
    committed: int = 0
    # duplicate traces for audit (capped)
    duplicate_traces: list[dict[str, Any]] = field(default_factory=list)

    def warm_from_db(self, db, *, limit: int = 50_000) -> int:
        """Load existing content hashes for the project into the cache."""
        from ..models import RawPost

        q = db.query(RawPost.id, RawPost.content_hash).filter(
            RawPost.content_hash.isnot(None),
            RawPost.content_hash != "",
        )
        if self.project_id is not None:
            from sqlalchemy import or_

            q = q.filter(or_(
                RawPost.project_id == self.project_id,
                RawPost.project_id.is_(None),
                RawPost.project_id == 0,
            ))
        n = 0
        for rid, ch in q.limit(limit).all():
            if not ch:
                continue
            self.seen.add(ch)
            self.masters.setdefault(ch, rid)
            n += 1
        return n

    def check(self, post: dict) -> dict[str, Any]:
        """Return decision for one incoming post.

        ``action``: ``accept`` | ``suppress_duplicate`` | ``skip_empty``
        """
        self.scraped += 1
        sig = post_content_signature(post)
        if not sig:
            return {"action": "skip_empty", "content_hash": "", "master_id": None}

        if sig in self.seen:
            self.suppressed += 1
            master_id = self.masters.get(sig)
            if len(self.duplicate_traces) < 100:
                self.duplicate_traces.append({
                    "content_hash": sig,
                    "master_id": master_id,
                    "platform": post.get("platform"),
                    "external_id": post.get("external_id"),
                    "url": (post.get("url") or "")[:200],
                })
            return {
                "action": "suppress_duplicate",
                "content_hash": sig,
                "master_id": master_id,
            }

        self.seen.add(sig)
        return {"action": "accept", "content_hash": sig, "master_id": None}

    def register_master(self, content_hash: str, raw_id: int) -> None:
        if content_hash:
            self.masters[content_hash] = raw_id
            self.committed += 1

    def finish(self) -> dict[str, Any]:
        """Flush telemetry counters for resolver-status."""
        _bump_telemetry(
            scraped=self.scraped,
            suppressed=self.suppressed,
            committed=self.committed,
        )
        summary = {
            "total_scraped_records": self.scraped,
            "suppressed_duplicate_records": self.suppressed,
            "clean_committed_records": self.committed,
            "duplicate_traces": list(self.duplicate_traces),
        }
        logger.info(
            "content_dedupe scraped=%s suppressed=%s committed=%s",
            self.scraped, self.suppressed, self.committed,
        )
        return summary


def backfill_and_purge_duplicates(db, *, project_id: Optional[int] = None) -> dict[str, Any]:
    """Hash existing rows and delete syndicated copies (keep earliest master).

    Use after deploying the gate so Live Feed / DMA are not stuck with historical
    FORUM+REDDIT clones of the same Accutane narrative.
    """
    from sqlalchemy import or_

    from ..models import ProcessedPost, RawPost

    q = db.query(RawPost)
    if project_id is not None:
        q = q.filter(or_(
            RawPost.project_id == project_id,
            RawPost.project_id.is_(None),
            RawPost.project_id == 0,
        ))

    rows = q.order_by(RawPost.id.asc()).all()
    masters: dict[str, RawPost] = {}
    purged = 0
    hashed = 0

    for raw in rows:
        sig = raw.content_hash or content_signature(raw.title or "", raw.body or "")
        if not sig:
            continue
        if not raw.content_hash:
            raw.content_hash = sig
            hashed += 1
        if sig not in masters:
            masters[sig] = raw
            continue
        master = masters[sig]
        master.duplicate_count = int(master.duplicate_count or 0) + 1 + int(raw.duplicate_count or 0)
        db.query(ProcessedPost).filter(ProcessedPost.raw_id == raw.id).delete(
            synchronize_session=False
        )
        db.delete(raw)
        purged += 1

    db.commit()
    _bump_telemetry(scraped=len(rows), suppressed=purged, committed=len(masters))
    return {
        "scanned": len(rows),
        "backfilled_hashes": hashed,
        "purged_duplicates": purged,
        "unique_masters": len(masters),
        "total_scraped_records": len(rows),
        "suppressed_duplicate_records": purged,
        "clean_committed_records": len(masters),
    }
