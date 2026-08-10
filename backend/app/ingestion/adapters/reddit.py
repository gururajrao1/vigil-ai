"""Social listening — Reddit REST/RSS + health subreddit streams."""
from __future__ import annotations

from typing import Any, Dict, List

from .base import IngestAdapter


class RedditAdapter(IngestAdapter):
    """Scraper/RSS adapters for /r/AskDocs, /r/pharmacy, and related health subs."""

    name = "reddit"

    DEFAULT_SUBS = ("AskDocs", "pharmacy", "AskPharmacists", "medicine")

    def fetch(self, **kwargs: Any) -> List[Dict[str, Any]]:
        mode = (kwargs.get("mode") or "health").lower()
        query = kwargs.get("query") or kwargs.get("q")
        limit = int(kwargs.get("limit", 25))
        posts: List[Dict[str, Any]] = []

        if mode == "rss":
            from ..sources import crawl_reddit_rss

            # crawl_reddit_rss returns a bare list
            posts = list(crawl_reddit_rss(query=query or "adverse event", limit=limit) or [])
        elif mode == "pullpush":
            from ..sources import crawl_reddit_pullpush

            result = crawl_reddit_pullpush(query=query or "adverse event", limit=limit)
            posts = result.get("posts") or []
        else:
            from ..sources import crawl_reddit_health

            result = crawl_reddit_health(query=query or "side effect", limit=limit)
            posts = result.get("posts") or []

        for p in posts:
            p.setdefault("platform", p.get("platform") or "reddit")
        return posts
