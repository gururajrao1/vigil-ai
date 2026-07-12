"""Step 2 — autonomous Pathfinder discovery loop.

Priority chain (offline-first):
  1. Self-hosted SearXNG metasearch
  2. Optional Exa / Tavily SaaS keys
  3. Curated offline seeds

DOM screening uses Firecrawl (self-hosted) when configured, else httpx + BS4.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PathfinderRun, Project, SuggestedSource
from .scope import project_keywords

logger = logging.getLogger("vigilai.pathfinder")

# DOM friction markers for login/paywall detection (EN + regional).
_AUTH_FRICTION_MARKERS = (
    "wp-login", "sign-in", "signin", "login-form", "log-in",
    "paywall-overlay", "subscription-wall", "members-only",
    "auth-required", "please log in", "please sign in",
    "登录", "註冊", "注册", "会員登録", "ログイン", "サインイン",
)

# Offline fallback: curated patient-community seeds by therapeutic area.
_OFFLINE_SEEDS: dict[str, list[dict[str, str]]] = {
    "oncology": [
        {"url": "https://www.cancer.org/treatment", "title": "ACS Treatment Communities"},
        {"url": "https://www.cancercare.org/", "title": "CancerCare Support"},
        {"url": "https://www.inspire.com/groups/advanced-breast-cancer/", "title": "Inspire Advanced BC"},
    ],
    "vaccine": [
        {"url": "https://www.immunize.org/", "title": "Immunize.org"},
        {"url": "https://www.vaccinesafety.edu/", "title": "Vaccine Safety Education"},
    ],
    "general": [
        {"url": "https://www.patientslikeme.com/", "title": "PatientsLikeMe"},
        {"url": "https://www.drugs.com/answers/", "title": "Drugs.com Q&A"},
        {"url": "https://www.reddit.com/r/AskDocs/", "title": "r/AskDocs"},
    ],
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def scan_auth_friction(html: str) -> tuple[str, list[str]]:
    """Inspect raw HTML for authentication / paywall friction tags."""
    flags: list[str] = []
    lower = (html or "").lower()
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup.find_all(True):
        attrs = " ".join(
            str(v).lower()
            for v in list(tag.attrs.values()) if isinstance(v, (str, list))
            for v in ([v] if isinstance(v, str) else v)
        )
        id_cls = f"{tag.get('id', '')} {tag.get('class', '')}".lower()
        blob = f"{attrs} {id_cls}"
        for marker in _AUTH_FRICTION_MARKERS:
            if marker in blob and marker not in flags:
                flags.append(marker)

    for marker in _AUTH_FRICTION_MARKERS:
        if marker in lower and marker not in flags:
            flags.append(marker)

    status = "login_required" if flags else "public"
    return status, flags


def _infer_searx_language(project: Project, keywords: list[str]) -> str:
    """Map therapeutic / regional intent to SearXNG language codes."""
    blob = " ".join(
        [project.therapeutic_area or "", project.description or "", " ".join(keywords)]
    ).lower()
    if any(ch in blob for ch in ("中国", "中文", "chinese", "zh-cn", "zh_cn")) or "china" in blob:
        return "zh-CN"
    if any(ch in blob for ch in ("日本", "日本語", "japanese")) or "japan" in blob:
        return "ja"
    if "한국" in blob or "korean" in blob or "korea" in blob:
        return "ko"
    return "en"


async def _search_searxng(
    query: str,
    *,
    language: str = "en",
    limit: int = 10,
) -> list[dict[str, str]]:
    """Query local SearXNG (`/search?format=json`). Empty if daemon unreachable."""
    base = settings.searxng_base_url
    if not base:
        return []
    params = {
        "q": query,
        "format": "json",
        "language": language,
        "categories": "general",
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(f"{base}/search", params=params)
            if r.status_code >= 400:
                logger.debug("SearXNG HTTP %s", r.status_code)
                return []
            data = r.json()
    except Exception as exc:
        logger.debug("SearXNG unreachable at %s: %s", base, exc)
        return []
    out: list[dict[str, str]] = []
    for hit in data.get("results", [])[:limit]:
        url = hit.get("url") or ""
        if url.startswith("http"):
            out.append({"url": url, "title": hit.get("title") or url})
    return out


def _fetch_html_firecrawl(url: str, timeout: float = 20.0) -> str:
    """Self-hosted Firecrawl scrape for JS-heavy pages. Returns HTML or ''."""
    base = settings.firecrawl_base_url
    if not base:
        return ""
    headers = {"Content-Type": "application/json"}
    if settings.firecrawl_api_key:
        headers["Authorization"] = f"Bearer {settings.firecrawl_api_key}"
    payload = {"url": url, "formats": ["html"], "onlyMainContent": False}
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{base}/v1/scrape", json=payload, headers=headers)
            if r.status_code >= 400:
                return ""
            data = r.json()
            # Firecrawl shapes vary: data.html | data.data.html
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            html = (inner or {}).get("html") or data.get("html") or ""
            return html if isinstance(html, str) else ""
    except Exception as exc:
        logger.debug("Firecrawl scrape failed for %s: %s", url, exc)
        return ""


def _fetch_html(url: str, timeout: float = 8.0) -> str:
    """Prefer Firecrawl for JS rendering; fall back to plain HTTP GET."""
    html = _fetch_html_firecrawl(url)
    if html:
        return html
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "VigilAI-Pathfinder/1.0"})
            if r.status_code < 400:
                return r.text
    except Exception as exc:
        logger.debug("HTML fetch failed for %s: %s", url, exc)
    return ""


async def _search_exa(query: str, limit: int = 8) -> list[dict[str, str]]:
    if not settings.exa_api_key:
        return []
    payload = {
        "query": query,
        "num_results": limit,
        "type": "neural",
        "use_autoprompt": True,
        "category": "company",
    }
    headers = {"x-api-key": settings.exa_api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post("https://api.exa.ai/search", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return [
        {"url": hit.get("url", ""), "title": hit.get("title") or hit.get("url", "")}
        for hit in data.get("results", [])
        if hit.get("url")
    ]


async def _search_tavily(query: str, limit: int = 8) -> list[dict[str, str]]:
    if not settings.tavily_api_key:
        return []
    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": limit,
        "include_domains": [],
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post("https://api.tavily.com/search", json=payload)
        r.raise_for_status()
        data = r.json()
    return [
        {"url": hit.get("url", ""), "title": hit.get("title") or hit.get("url", "")}
        for hit in data.get("results", [])
        if hit.get("url")
    ]


def _offline_discover(project: Project, keywords: list[str]) -> list[dict[str, str]]:
    area = (project.therapeutic_area or "general").lower()
    seeds = list(_OFFLINE_SEEDS.get(area, [])) + list(_OFFLINE_SEEDS.get("general", []))
    extra = []
    for kw in keywords[:3]:
        slug = re.sub(r"[^a-z0-9]+", "-", kw.lower())[:40]
        extra.append({
            "url": f"https://www.reddit.com/search/?q={kw.replace(' ', '+')}",
            "title": f"Reddit search: {kw}",
        })
        extra.append({
            "url": f"https://patient.info/search?q={slug}",
            "title": f"Patient.info: {kw}",
        })
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in seeds + extra:
        u = item["url"]
        if u not in seen:
            seen.add(u)
            out.append(item)
    return out[:12]


async def run_pathfinder(db: Session, project: Project) -> PathfinderRun:
    """Execute intent-driven discovery and enqueue suggested sources."""
    keywords = project_keywords(project)
    intent = (
        f"patient forums and communities discussing "
        f"{' '.join(keywords[:5]) or project.therapeutic_area or 'drug adverse events'} "
        f"including regional boards China Japan niche specialty sites"
    )

    run = PathfinderRun(
        project_id=project.id,
        status="running",
        query_used=intent,
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    provider = "offline"
    hits: list[dict[str, str]] = []
    lang = _infer_searx_language(project, keywords)
    try:
        # 1) Self-hosted SearXNG (preferred — no SaaS key)
        hits = await _search_searxng(intent, language=lang)
        if hits:
            provider = "searxng"
        else:
            # Regional second pass for CJK specialty boards
            if lang == "en":
                for alt_lang, alt_q in (
                    ("zh-CN", intent + " 患者论坛 不良反应"),
                    ("ja", intent + " 患者会 副作用"),
                ):
                    hits = await _search_searxng(alt_q, language=alt_lang)
                    if hits:
                        provider = f"searxng:{alt_lang}"
                        break
        if not hits:
            hits = await _search_exa(intent)
            if hits:
                provider = "exa"
        if not hits:
            hits = await _search_tavily(intent)
            if hits:
                provider = "tavily"
        if not hits:
            hits = _offline_discover(project, keywords)
            provider = "offline"
    except Exception as exc:
        logger.warning("Pathfinder search failed, using offline seeds: %s", exc)
        hits = _offline_discover(project, keywords)
        provider = "offline"

    discovered: list[dict[str, Any]] = []
    for hit in hits:
        url = hit.get("url", "").strip()
        if not url or not url.startswith("http"):
            continue
        html = _fetch_html(url)
        access_status, flags = scan_auth_friction(html)
        row = SuggestedSource(
            project_id=project.id,
            url=url[:1024],
            domain=_domain(url),
            title=(hit.get("title") or url)[:512],
            access_status=access_status,
            access_flags_json=json.dumps(flags),
            approval_status="pending",
            discovery_run_id=run.id,
        )
        db.add(row)
        discovered.append({
            "url": url,
            "title": hit.get("title"),
            "access_status": access_status,
            "flags": flags,
        })

    run.status = "completed"
    run.provider = provider
    run.urls_discovered = len(discovered)
    run.result_json = json.dumps(discovered)
    run.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run
