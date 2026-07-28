"""MCP-lite agent console — chat slot-filling that dispatches VigilAI crawls.

Mirrors Algo-Pharma's conversational crawl dispatcher without requiring Groq/MCP:
parse intent (source + query) → call existing crawl functions → return narrative.

Hardened for the Data Sources → Agent chat UI:
- meta / help prompts never hit the network
- crawl + ingest errors become soft replies (no uncaught 500)
- full corpus recompute is skipped on chat (too slow / timeout-prone)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..ingestion.sources import (
    crawl_dailymed_rss,
    crawl_cochrane_central,
    crawl_europe_pmc,
    crawl_faers,
    crawl_google_news,
    crawl_hackernews,
    crawl_life_science_news,
    crawl_maude_live,
    crawl_mhra_devices,
    crawl_pubmed_live,
    crawl_reddit_health,
    crawl_reddit_pullpush,
    crawl_semantic_scholar,
    crawl_youtube,
)
from ..pipeline import ingest_posts

logger = logging.getLogger("vigilai.agentic.chat")

# Longer aliases first so "life science news" does not collapse to google "news".
_SOURCE_ALIASES: List[Tuple[str, Tuple[str, ...]]] = [
    ("life_science", (
        "life science", "life-science", "sciencedaily", "nature medicine",
        "pharma news", "endpoints", "stat news",
    )),
    ("google_news", ("google news", "google_news", "rss news", "news")),
    ("hackernews", ("hackernews", "hacker news", "hn")),
    ("youtube", ("youtube", "yt comments", "youtube comments", "yt")),
    ("faers", ("faers", "openfda", "icsr", "fda ae", "fda adverse")),
    ("pubmed", ("pubmed", "medline", "ncbi", "papers")),
    ("europe_pmc", ("europe pmc", "europepmc", "epmc")),
    ("semantic_scholar", ("semantic scholar", "semanticscholar", "s2 papers")),
    ("cochrane", ("cochrane central", "cochrane", "cctr")),
    ("literature", ("literature", "abstracts", "medical abstract")),
    ("reddit", ("reddit", "pullpush", "subreddit", "r/")),
    ("maude", ("maude", "device adverse", "device event")),
    ("mhra", ("mhra", "yellow card", "uk device")),
    ("dailymed", ("dailymed", "daily med", "drug label", "labels")),
]

_UNSUPPORTED = {
    "twitter": "X/Twitter needs TWITTERAPI_IO_KEY. Try Google News or Reddit instead.",
    "x.com": "X/Twitter needs TWITTERAPI_IO_KEY. Try Google News or Reddit instead.",
    "tweet": "X/Twitter needs TWITTERAPI_IO_KEY. Try Google News or Reddit instead.",
}

_HELP_RE = re.compile(
    r"^\s*(?:help|hi|hello|hey|status|what can you do\??|capabilities|sources|"
    r"list sources|how do i|commands|\?)\s*[.!]?\s*$",
    re.I,
)

_QUERY_HINTS = re.compile(
    r"(?:about|for|on|regarding|query[=:\s]+|search(?:ing)?(?:\s+for)?|"
    r"looking for|find)\s+(.+)$",
    re.I,
)

_LIMIT_RE = re.compile(r"\blimit\s*[:=]?\s*(\d{1,3})\b", re.I)

_HELP_REPLY = (
    "I crawl and ingest into VigilAI. Try:\n"
    "• crawl google news about ozempic side effects\n"
    "• fetch reddit for accutane depression\n"
    "• pull faers\n"
    "• search pubmed for myocarditis vaccine\n"
    "• europe pmc abstracts about statin myalgia\n"
    "• semantic scholar pharmacovigilance signal\n"
    "• cochrane central vaccine safety\n"
    "• youtube vaccine side effects\n"
    "• life science news\n"
    "• hacker news about drug safety\n"
    "• pull maude / mhra / dailymed\n"
    "Sources: google_news · life_science · reddit · faers · pubmed · europe_pmc · "
    "semantic_scholar · cochrane · youtube · hackernews · maude · mhra · dailymed.\n"
    "Tip: literature sources ingest abstracts (not ICSRs). Add `limit 10` for small batches."
)


def parse_intent(message: str) -> Dict[str, Any]:
    """Extract source + search query (+ optional limit) from a short NL request."""
    text = (message or "").strip()
    low = text.lower()

    if not text or _HELP_RE.match(text):
        return {
            "slots": {"source": None, "query": None, "limit": 15},
            "missing": [],
            "raw": text,
            "mode": "help",
            "unsupported": None,
        }

    unsupported = None
    for needle, tip in _UNSUPPORTED.items():
        if needle in low:
            unsupported = tip
            break

    source = None
    for sid, aliases in _SOURCE_ALIASES:
        if any(a in low for a in aliases):
            source = sid
            break
    if source is None and unsupported is None:
        source = "google_news"

    limit = 15
    lm = _LIMIT_RE.search(text)
    if lm:
        limit = max(3, min(40, int(lm.group(1))))

    query = None
    m = _QUERY_HINTS.search(text)
    if m:
        query = m.group(1).strip(" .!?\"'")
    else:
        cleaned = low
        for _, aliases in _SOURCE_ALIASES:
            for a in sorted(aliases, key=len, reverse=True):
                cleaned = cleaned.replace(a, " ")
        for needle in _UNSUPPORTED:
            cleaned = cleaned.replace(needle, " ")
        for noise in (
            "crawl", "fetch", "ingest", "pull", "get", "run", "please", "me",
            "the", "some", "posts", "data", "and", "then", "now",
        ):
            cleaned = re.sub(rf"\b{noise}\b", " ", cleaned)
        cleaned = _LIMIT_RE.sub(" ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .!?")
        if len(cleaned) >= 3:
            query = cleaned

    # Strip limit fragment leftover in query
    if query:
        query = _LIMIT_RE.sub(" ", query)
        query = re.sub(r"\s+", " ", query).strip(" .!?\"'")
        if len(query) < 3:
            query = None

    return {
        "slots": {"source": source, "query": query or None, "limit": limit},
        "missing": [],
        "raw": text,
        "mode": "crawl",
        "unsupported": unsupported,
    }


def _normalize_batch(batch: Any) -> Tuple[List[dict], dict]:
    if isinstance(batch, list):
        return batch, {"posts": batch, "unique_fetched": len(batch)}
    if not isinstance(batch, dict):
        return [], {"posts": [], "note": f"Unexpected crawl payload type: {type(batch).__name__}"}
    posts = batch.get("posts") or []
    if not isinstance(posts, list):
        posts = []
    return posts, batch


def _run_crawl(source: str, query: Optional[str], limit: int) -> dict:
    if source == "google_news":
        return crawl_google_news(query=query, limit=limit)
    if source == "life_science":
        # Free-text query is not a feed id — prefer Google News for topical search,
        # otherwise crawl the life-science RSS pack.
        if query and (" " in query or len(query) > 24):
            return crawl_google_news(query=query, limit=limit)
        return crawl_life_science_news(
            feed_id=query if query and " " not in query else None,
            limit=limit,
        )
    if source == "hackernews":
        return crawl_hackernews(query=query, limit=limit)
    if source == "youtube":
        return crawl_youtube(query=query, limit=min(limit, 10))
    if source == "faers":
        return crawl_faers(limit=limit)
    if source == "pubmed" or source == "literature":
        return crawl_pubmed_live(query=query, limit=limit)
    if source == "europe_pmc":
        return crawl_europe_pmc(query=query, limit=limit)
    if source == "semantic_scholar":
        return crawl_semantic_scholar(query=query, limit=limit)
    if source == "cochrane":
        return crawl_cochrane_central(query=query, limit=limit)
    if source == "reddit":
        q = query or "side effect adverse reaction"
        batch = crawl_reddit_pullpush(query=q, limit=limit)
        posts, meta = _normalize_batch(batch)
        if posts:
            return meta
        # Pullpush empty / blocked → health RSS fallback
        return crawl_reddit_health(query=q, limit=limit)
    if source == "maude":
        return crawl_maude_live(limit=limit)
    if source == "mhra":
        return crawl_mhra_devices(limit=limit)
    if source == "dailymed":
        return crawl_dailymed_rss(limit=limit)
    return crawl_google_news(query=query, limit=limit)


def dispatch(db: Session, message: str, execute: bool = True) -> Dict[str, Any]:
    """Parse → (optional) crawl+ingest → reply suitable for the Agent chat UI."""
    try:
        return _dispatch_inner(db, message, execute=execute)
    except Exception as exc:
        logger.exception("agent chat dispatch failed: %s", exc)
        return {
            "status": "error",
            "parsed": {"slots": {}, "raw": message, "mode": "error"},
            "fetched": 0,
            "ingested": 0,
            "reply": (
                f"Something went wrong running that command ({type(exc).__name__}: {exc}). "
                "Try a smaller batch (`limit 5`) or another source, e.g. "
                "`fetch google news about ozempic`."
            ),
        }


def _dispatch_inner(db: Session, message: str, execute: bool = True) -> Dict[str, Any]:
    parsed = parse_intent(message)

    if parsed.get("mode") == "help":
        return {
            "status": "help",
            "parsed": parsed,
            "fetched": 0,
            "ingested": 0,
            "reply": _HELP_REPLY,
        }

    if parsed.get("unsupported"):
        return {
            "status": "unsupported",
            "parsed": parsed,
            "fetched": 0,
            "ingested": 0,
            "reply": parsed["unsupported"],
        }

    slots = parsed["slots"]
    if not slots.get("source"):
        return {
            "status": "need_slots",
            "parsed": parsed,
            "fetched": 0,
            "ingested": 0,
            "reply": _HELP_REPLY,
        }

    if not execute:
        return {
            "status": "planned",
            "parsed": parsed,
            "fetched": 0,
            "ingested": 0,
            "reply": (
                f"Plan: source={slots['source']}, query={slots['query']!r}, "
                f"limit={slots['limit']}. Send again with execute=true to run."
            ),
        }

    try:
        batch = _run_crawl(slots["source"], slots["query"], int(slots["limit"] or 15))
    except Exception as exc:
        logger.exception("crawl failed source=%s query=%s", slots["source"], slots["query"])
        return {
            "status": "error",
            "parsed": parsed,
            "fetched": 0,
            "ingested": 0,
            "reply": (
                f"Crawl **{slots['source']}** failed ({type(exc).__name__}: {exc}). "
                "Try another source or a simpler query."
            ),
        }

    posts, batch = _normalize_batch(batch)
    note = batch.get("note")
    feed_errors = batch.get("feed_errors")

    if not posts:
        reply = (
            f"Dispatched **{slots['source']}**"
            + (f" query={slots['query']!r}" if slots["query"] else "")
            + " → fetched 0 posts."
        )
        if note:
            reply += f" Note: {note}"
        if feed_errors:
            reply += f" Feed issues: {'; '.join(map(str, feed_errors[:3]))}"
        reply += " Try a different source/query, or `pull faers` / `life science news`."
        return {
            "status": "empty",
            "parsed": parsed,
            "fetched": 0,
            "ingested": 0,
            "note": note,
            "reply": reply,
        }

    try:
        new = ingest_posts(
            db, posts,
            use_transformer=False,
            use_presidio=False,
            online_translation=False,
        )
    except Exception as exc:
        logger.exception("ingest failed after %s crawl", slots["source"])
        try:
            db.rollback()
        except Exception:
            pass
        return {
            "status": "error",
            "parsed": parsed,
            "fetched": len(posts),
            "ingested": 0,
            "reply": (
                f"Fetched {len(posts)} from **{slots['source']}** but ingest failed "
                f"({type(exc).__name__}: {exc})."
            ),
        }

    # Skip full recompute_signals here — it can take minutes and trip proxy timeouts.
    # Corpus posts are durable; user can Refresh / Recompute from the Demo bar.
    reply = (
        f"Dispatched **{slots['source']}**"
        + (f" query={slots['query']!r}" if slots["query"] else "")
        + f" → fetched {len(posts)}, ingested {new}."
        + " Open Live Feed / Dashboard to review; run **Recompute** when you want signals refreshed."
    )
    if note:
        reply += f" Note: {note}"
    if feed_errors:
        reply += f" Partial feed issues: {'; '.join(map(str, feed_errors[:2]))}"

    return {
        "status": "ok",
        "parsed": parsed,
        "fetched": len(posts),
        "ingested": new,
        "note": note,
        "stats": {"recomputed": False, "deferred": True},
        "reply": reply,
    }
