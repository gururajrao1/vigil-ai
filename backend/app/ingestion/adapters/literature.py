"""Literature / clinical narrative connectors (PubMed, Europe PMC, S2, Cochrane).

Inspired by II-Commons / Pubrunner-style background literature ingestion from
awesome-bioie — implemented as thin wrappers over VigilAI's keyless crawlers.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import IngestAdapter


class LiteratureAdapter(IngestAdapter):
    """PubMed / PMC-style abstract ingest (XML/Markdown-ready text bodies)."""

    name = "literature"

    def fetch(self, **kwargs: Any) -> List[Dict[str, Any]]:
        source = (kwargs.get("source") or "pubmed").lower()
        query = kwargs.get("query") or kwargs.get("q")
        limit = int(kwargs.get("limit", 20))
        posts: List[Dict[str, Any]] = []

        if source in ("pubmed", "medline", "all"):
            from ..literature import crawl_pubmed_abstracts

            posts.extend((crawl_pubmed_abstracts(query=query, limit=limit) or {}).get("posts") or [])
        if source in ("europe_pmc", "epmc", "all"):
            from ..literature import crawl_europe_pmc

            posts.extend((crawl_europe_pmc(query=query, limit=limit) or {}).get("posts") or [])
        if source in ("semantic_scholar", "s2", "all"):
            from ..literature import crawl_semantic_scholar

            posts.extend((crawl_semantic_scholar(query=query, limit=limit) or {}).get("posts") or [])
        if source in ("cochrane", "cochrane_central", "all"):
            from ..literature import crawl_cochrane_central

            posts.extend((crawl_cochrane_central(query=query, limit=limit) or {}).get("posts") or [])

        for p in posts:
            p.setdefault("platform", p.get("platform") or "pubmed")
            p.setdefault("product_type", "drug")
        return posts
