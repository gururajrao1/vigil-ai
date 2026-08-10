"""openFDA MAUDE REST adapter — wraps VigilAI ``crawl_maude_live`` connector."""
from __future__ import annotations

from typing import Any, Dict, List

from .base import IngestAdapter


class MaudeAdapter(IngestAdapter):
    """Device spontaneous reports: https://api.fda.gov/device/event.json"""

    name = "openfda_maude"

    def fetch(self, **kwargs: Any) -> List[Dict[str, Any]]:
        from ..sources import crawl_maude_live

        limit = int(kwargs.get("limit", 30))
        result = crawl_maude_live(limit=limit)
        posts = result.get("posts") or []
        for p in posts:
            p.setdefault("platform", "maude")
            p.setdefault("product_type", "device")
        return posts
