"""MCP-lite agent console — chat slot-filling that dispatches VigilAI crawls.

Mirrors Algo-Pharma's conversational crawl dispatcher without requiring Groq/MCP:
parse intent (source + query) → call existing crawl functions → return narrative.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..ingestion.sources import (
    crawl_faers,
    crawl_google_news,
    crawl_hackernews,
    crawl_life_science_news,
    crawl_pubmed_live,
    crawl_reddit_pullpush,
    crawl_youtube,
)
from ..pipeline import ingest_posts, recompute_signals

_SOURCE_ALIASES: List[Tuple[str, Tuple[str, ...]]] = [
    ("google_news", ("google news", "news", "rss news")),
    ("life_science", ("life science", "stat", "sciencedaily", "nature medicine", "pharma news")),
    ("hackernews", ("hackernews", "hacker news", "hn")),
    ("youtube", ("youtube", "yt comments", "youtube comments")),
    ("faers", ("faers", "openfda", "icsr")),
    ("pubmed", ("pubmed", "literature", "papers")),
    ("reddit", ("reddit", "pullpush", "subreddit")),
]

_QUERY_HINTS = re.compile(
    r"(?:about|for|on|regarding|query|search(?:ing)?(?:\s+for)?)\s+(.+)$",
    re.I,
)


def parse_intent(message: str) -> Dict[str, Any]:
    """Extract source + search query from a short natural-language request."""
    text = (message or "").strip()
    low = text.lower()
    source = None
    for sid, aliases in _SOURCE_ALIASES:
        if any(a in low for a in aliases):
            source = sid
            break
    if source is None:
        # bare drug/AE phrases → default google news
        source = "google_news"

    query = None
    m = _QUERY_HINTS.search(text)
    if m:
        query = m.group(1).strip(" .!?\"'")
    else:
        # strip source words and keep remainder as query
        cleaned = low
        for _, aliases in _SOURCE_ALIASES:
            for a in aliases:
                cleaned = cleaned.replace(a, " ")
        for noise in ("crawl", "fetch", "ingest", "pull", "get", "run", "please", "me"):
            cleaned = re.sub(rf"\b{noise}\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .!?")
        if len(cleaned) >= 4:
            query = cleaned

    slots = {"source": source, "query": query or None, "limit": 15}
    missing = []
    if not slots["source"]:
        missing.append("source")
    return {"slots": slots, "missing": missing, "raw": text}


def _run_crawl(source: str, query: Optional[str], limit: int) -> dict:
    if source == "google_news":
        return crawl_google_news(query=query, limit=limit)
    if source == "life_science":
        return crawl_life_science_news(feed_id=query if query and " " not in query else None,
                                       limit=limit)
    if source == "hackernews":
        return crawl_hackernews(query=query, limit=limit)
    if source == "youtube":
        return crawl_youtube(query=query, limit=min(limit, 10))
    if source == "faers":
        return crawl_faers(limit=limit)
    if source == "pubmed":
        return crawl_pubmed_live(query=query, limit=limit)
    if source == "reddit":
        return crawl_reddit_pullpush(query=query or "side effect adverse reaction", limit=limit)
    return crawl_google_news(query=query, limit=limit)


def dispatch(db: Session, message: str, execute: bool = True) -> Dict[str, Any]:
    """Parse → (optional) crawl+ingest → reply suitable for the Command Center UI."""
    parsed = parse_intent(message)
    slots = parsed["slots"]
    if parsed["missing"]:
        return {
            "status": "need_slots",
            "parsed": parsed,
            "reply": (
                "I can crawl Google News, life-science RSS, HackerNews, YouTube, "
                "FAERS, PubMed, or Reddit (Pullpush). Try: "
                "\"crawl youtube about ozempic side effects\""
            ),
        }

    if not execute:
        return {
            "status": "planned",
            "parsed": parsed,
            "reply": (
                f"Plan: source={slots['source']}, query={slots['query']!r}, "
                f"limit={slots['limit']}. Send again with execute=true to run."
            ),
        }

    batch = _run_crawl(slots["source"], slots["query"], slots["limit"])
    posts = batch.get("posts") or []
    # list-returning crawlers
    if isinstance(batch, list):
        posts = batch
        batch = {"posts": posts, "unique_fetched": len(posts)}

    new = ingest_posts(db, posts, use_transformer=False,
                       use_presidio=False, online_translation=False)
    # Light recompute — presentation console should stay responsive
    stats = recompute_signals(db, use_fda=False, with_narrative=False)
    note = batch.get("note")
    reply = (
        f"Dispatched **{slots['source']}**"
        + (f" query={slots['query']!r}" if slots["query"] else "")
        + f" → fetched {len(posts)}, ingested {new}."
    )
    if note:
        reply += f" Note: {note}"
    return {
        "status": "ok",
        "parsed": parsed,
        "fetched": len(posts),
        "ingested": new,
        "note": note,
        "stats": stats,
        "reply": reply,
    }
