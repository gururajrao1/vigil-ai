"""PubMed (NCBI E-utilities) literature connector — NO API key required.

Counts published articles linking a product to an adverse event and returns the
top article (title + PMID + link). This is real, citable literature evidence.
Keyless but rate-limited, so we cache aggressively and time out fast, degrading to
a deterministic offline result when there is no network.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import httpx

from ..config import settings

_CACHE: Dict[str, tuple[float, dict]] = {}
_TTL = 6 * 3600

_ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def _offline(term: str, event: str) -> dict:
    return {
        "available": False,
        "source": "pubmed_offline",
        "count": 0,
        "top": None,
        "query": f"{term} AND {event}",
    }


def query_pubmed(product: str, event: str, timeout: float = 3.0) -> dict:
    """esearch (count + top PMID) then esummary (title). Cached by (product,event)."""
    product = (product or "").strip().lower()
    event = (event or "").strip().lower()
    key = f"pm::{product}|{event}"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]

    term = f'("{product}"[tiab]) AND ("{event}"[tiab]) AND (adverse OR "side effect" OR safety)'
    result: Optional[dict] = None
    try:
        base = settings.pubmed_base_url
        es = httpx.get(
            f"{base}/esearch.fcgi",
            params={"db": "pubmed", "term": term, "retmode": "json", "retmax": 1},
            timeout=timeout,
        )
        if es.status_code == 200:
            r = es.json().get("esearchresult", {})
            count = int(r.get("count", 0) or 0)
            idlist = r.get("idlist", []) or []
            top = None
            if idlist:
                pmid = idlist[0]
                title = None
                try:
                    summ = httpx.get(
                        f"{base}/esummary.fcgi",
                        params={"db": "pubmed", "id": pmid, "retmode": "json"},
                        timeout=timeout,
                    )
                    if summ.status_code == 200:
                        title = summ.json().get("result", {}).get(pmid, {}).get("title")
                except Exception:
                    title = None
                top = {"pmid": pmid, "title": title, "url": _ARTICLE_URL.format(pmid=pmid)}
            result = {
                "available": count > 0,
                "source": "pubmed",
                "count": count,
                "top": top,
                "query": term,
            }
    except Exception:
        result = None

    if result is None:
        result = _offline(product, event)

    _CACHE[key] = (now, result)
    return result
