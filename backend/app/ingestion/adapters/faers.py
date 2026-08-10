"""openFDA FAERS REST adapter — wraps VigilAI ``crawl_faers`` connector."""
from __future__ import annotations

from typing import Any, Dict, List

from .base import IngestAdapter


class FaersAdapter(IngestAdapter):
    """Regulatory spontaneous reports: https://api.fda.gov/drug/event.json"""

    name = "openfda_faers"

    def fetch(self, **kwargs: Any) -> List[Dict[str, Any]]:
        from ..sources import crawl_faers

        limit = int(kwargs.get("limit", 30))
        days_back = int(kwargs.get("days_back", 90))
        result = crawl_faers(limit=limit, days_back=days_back)
        posts = result.get("posts") or []
        for p in posts:
            p.setdefault("platform", "faers")
            p.setdefault("product_type", "drug")
        return posts
