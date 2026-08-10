"""Offline-first capability probes — single source of truth for degradation modes."""
from __future__ import annotations

import os

import httpx

from ..config import settings


def _playwright_available() -> bool:
    try:
        from importlib.util import find_spec

        return find_spec("playwright") is not None
    except Exception:
        return False


def _presidio_available() -> bool:
    """Report Presidio availability WITHOUT building the engine.

    Building the analyzer loads the spaCy model (~60s cold), which turned
    /api/health and pipeline_capabilities into a gateway-timeout on first hit.
    Report the already-built engine if present, else probe importability with
    find_spec; the real engine still builds lazily on the first PII scrub.
    """
    if not settings.use_presidio:
        return False
    from .. import nlp  # noqa: F401
    from ..nlp import pii as _pii

    if _pii._ANALYZER is not None:
        return True
    if _pii._PRESIDIO_TRIED:  # already attempted and failed — don't retry here
        return _pii._ANALYZER is not None
    try:
        from importlib.util import find_spec

        return bool(find_spec("presidio_analyzer") and find_spec("en_core_web_sm"))
    except Exception:
        return False


def _storage_state_configured() -> bool:
    profile_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "browser_profiles", "cookies.json"
    )
    vault = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "project_vault",
        "cookies.json",
    )
    if settings.playwright_storage_state_path and os.path.isfile(settings.playwright_storage_state_path):
        return True
    return os.path.isfile(profile_dir) or os.path.isfile(vault)


def _searxng_reachable() -> bool:
    base = settings.searxng_base_url
    if not base:
        return False
    try:
        r = httpx.get(f"{base}/", timeout=0.4)
        return r.status_code < 500
    except Exception:
        return False


def pipeline_capabilities() -> dict:
    """Report which optional services are live vs deterministic fallback."""
    searx = _searxng_reachable()
    return {
        "pathfinder": {
            "searxng": searx,
            "searxng_url": settings.searxng_base_url,
            "firecrawl": bool(settings.firecrawl_base_url),
            "exa": bool(settings.exa_api_key),
            "tavily": bool(settings.tavily_api_key),
            "offline_seeds": True,
            "fallback": (
                "searxng -> exa/tavily -> offline_seeds"
                if searx
                else "exa/tavily -> offline_seeds"
            ),
        },
        "source_crawl": {
            "playwright_installed": _playwright_available(),
            "storage_state_configured": _storage_state_configured(),
            "httpx_fallback": True,
            "fallback": "httpx" if not _playwright_available() else "playwright_then_httpx",
        },
        "privacy": {
            "presidio_enabled": settings.use_presidio,
            "presidio_available": _presidio_available(),
            "regex_layer": True,
            "fallback": "regex_only" if not _presidio_available() else "presidio+regex",
        },
        "registries": {
            "kaers": "offline_fixture",
            "cochrane_central": "europe_pmc_src_cctr_or_offline",
            "medline_pubmed": "eutils_efetch_abstracts_or_offline",
            "europe_pmc": "rest_or_offline",
            "semantic_scholar": "graph_api_or_offline",
        },
        "disproportionality": {
            "prr": True,
            "ror": True,
            "ic_ic025": True,
            "ebgm_eb05": True,
            "logistic_confounding": True,
        },
        "story": {
            "endpoint": "/api/story",
            "pdf": True,
        },
        "molecular": {
            "stitch_offline_kb": True,
            "min_confidence": 0.700,
            "species": 9606,
        },
        "divergence": {
            "openfda_configured": True,
            "offline_kb": True,
            "flat_baseline": True,
            "fallback": "openfda -> offline_kb -> flat_baseline",
        },
    }
