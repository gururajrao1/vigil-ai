"""Multi-source registry adapters: KAERS, Cochrane CENTRAL, MEDLINE/PubMed.

Each adapter normalizes heterogeneous payloads into VigilAI ingest post dicts.
Network calls degrade to empty lists; offline fixtures remain available for demos.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("vigilai.registry_adapters")


def _post(
    *,
    external_id: str,
    platform: str,
    title: str,
    body: str,
    url: str = "",
    region: str = "Global",
    country: str = "",
    language: str = "en",
) -> dict[str, Any]:
    return {
        "external_id": external_id,
        "platform": platform,
        "url": url,
        "title": (title or "")[:500],
        "body": (body or "")[:4000],
        "region": region,
        "country": country,
        "language": language,
        "posted_at": datetime.utcnow().isoformat(),
    }


# --------------------------------------------------------------------------- #
# KAERS (Korean Adverse Event Reporting System) — public summary surrogate
# --------------------------------------------------------------------------- #
_KAERS_OFFLINE = [
    {
        "drug": "metformin",
        "event": "lactic acidosis",
        "narrative": "KAERS case summary: metformin associated lactic acidosis in elderly patient with renal impairment.",
        "country": "KR",
    },
    {
        "drug": "clopidogrel",
        "event": "gastrointestinal haemorrhage",
        "narrative": "KAERS: clopidogrel with GI bleeding after dual antiplatelet therapy.",
        "country": "KR",
    },
]


def fetch_kaers(query: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """Normalize KAERS-style rows. Live API is not publicly keyless — offline fixture."""
    q = (query or "").lower()
    rows = _KAERS_OFFLINE
    if q:
        rows = [r for r in rows if q in r["drug"] or q in r["event"] or q in r["narrative"].lower()]
    out = []
    for i, r in enumerate(rows[:limit]):
        out.append(
            _post(
                external_id=f"kaers:{r['drug']}:{r['event']}:{i}",
                platform="kaers",
                title=f"KAERS: {r['drug']} — {r['event']}",
                body=r["narrative"],
                url="https://nedrug.mfds.go.kr/pbp/CCBBB01/getList",
                region="Asia",
                country=r.get("country") or "KR",
                language="ko",
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Cochrane CENTRAL — trial register abstracts (via Cochrane Library search HTML/API surrogate)
# --------------------------------------------------------------------------- #
_COCHRANE_OFFLINE = [
    {
        "id": "cn-01234567",
        "title": "Statins for primary prevention — adverse event meta-analysis",
        "abstract": "CENTRAL record: myalgia and elevated CK reported more frequently with high-intensity statin arms.",
    },
    {
        "id": "cn-07654321",
        "title": "Immune checkpoint inhibitors and immune-related adverse events",
        "abstract": "CENTRAL: colitis, pneumonitis, and hypothyroidism as AESI clusters in ICI trials.",
    },
]


def fetch_cochrane_central(query: str = "adverse event", limit: int = 20) -> list[dict[str, Any]]:
    """Cochrane CENTRAL — Europe PMC SRC:cctr with offline fixtures."""
    from .literature import crawl_cochrane_central

    return list((crawl_cochrane_central(query=query, limit=limit).get("posts") or []))


# --------------------------------------------------------------------------- #
# MEDLINE / PubMed — E-utilities (no key required; NCBI key raises rate limit)
# --------------------------------------------------------------------------- #
def fetch_medline_pubmed(query: str = "drug adverse effects", limit: int = 20) -> list[dict[str, Any]]:
    """Fetch PubMed abstracts via literature module (efetch); offline on failure."""
    from .literature import crawl_pubmed_abstracts

    posts = list((crawl_pubmed_abstracts(query=query, limit=limit).get("posts") or []))
    for p in posts:
        p["platform"] = "medline_pubmed"
        ext = p.get("external_id") or ""
        if ext.startswith("pubmed_"):
            p["external_id"] = ext.replace("pubmed_", "pubmed:", 1)
    return posts


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    """Legacy helper; prefer literature._parse_pubmed_xml."""
    from .literature import _parse_pubmed_xml as _lit_parse

    return _lit_parse(xml_text, platform="medline_pubmed")


def _medline_offline(query: str, limit: int) -> list[dict[str, Any]]:
    from .literature import crawl_pubmed_abstracts

    return list((crawl_pubmed_abstracts(query=query, limit=limit).get("posts") or []))


def fetch_multi_registry(query: str = "adverse event", limit_per: int = 10) -> dict[str, list[dict[str, Any]]]:
    """Fan-out across KAERS + Cochrane + MEDLINE for cross-sectional mining."""
    return {
        "kaers": fetch_kaers(query, limit_per),
        "cochrane_central": fetch_cochrane_central(query, limit_per),
        "medline_pubmed": fetch_medline_pubmed(query, limit_per),
    }
