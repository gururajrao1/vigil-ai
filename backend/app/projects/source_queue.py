"""Step 3 — Suggested Source Queue + Playwright headless authentication bypass."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..config import settings
from ..models import SuggestedSource
from ..pipeline import ingest_posts, recompute_signals

logger = logging.getLogger("vigilai.source_queue")

_PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "browser_profiles")
_MAX_BODY = 4000
_BINARY_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _resolve_storage_state(profile: Optional[str]) -> Optional[str]:
    """Map a storage profile name to a local Playwright storage_state JSON path.

    Lookup order:
      1. Named profile under browser_profiles/
      2. PLAYWRIGHT_STORAGE_STATE_PATH env
      3. browser_profiles/cookies.json
      4. project_vault/cookies.json (spec vault path)
    """
    if profile:
        path = os.path.join(_PROFILE_DIR, profile if profile.endswith(".json") else f"{profile}.json")
        if os.path.isfile(path):
            return path
    if settings.playwright_storage_state_path and os.path.isfile(settings.playwright_storage_state_path):
        return settings.playwright_storage_state_path
    default = os.path.join(_PROFILE_DIR, "cookies.json")
    if os.path.isfile(default):
        return default
    vault = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "project_vault",
        "cookies.json",
    )
    return vault if os.path.isfile(vault) else None


def _looks_like_pdf(url: str, content_type: str = "", sample: bytes = b"") -> bool:
    path = urlparse(url).path.lower()
    if path.endswith(".pdf") or ".pdf?" in url.lower():
        return True
    ct = (content_type or "").lower()
    if "application/pdf" in ct:
        return True
    return sample[:5] == b"%PDF-"


def _extract_pdf_text(data: bytes, url: str) -> Optional[dict]:
    """Extract plain text from a PDF; returns a post dict or None."""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        chunks: list[str] = []
        for page in reader.pages[:12]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        text = re.sub(r"\s+", " ", " ".join(chunks)).strip()
        if len(text) < 40:
            return None
        title = (reader.metadata.title if reader.metadata else None) or urlparse(url).path.split("/")[-1] or "PDF document"
        return {
            "external_id": f"pdf:{url}",
            "platform": "pathfinder",
            "url": url,
            "title": str(title)[:500],
            "body": text[:_MAX_BODY],
            "region": "Global",
        }
    except ImportError:
        logger.warning("pypdf not installed — cannot extract text from PDF %s", url)
        return None
    except Exception as exc:
        logger.warning("PDF extract failed for %s: %s", url, exc)
        return None


def _sanitize_text(text: str) -> str:
    """Drop control/binary noise and collapse whitespace for feed display."""
    if not text:
        return ""
    if text.lstrip().startswith("%PDF-") or _BINARY_RE.search(text[:2000]):
        return ""
    cleaned = _BINARY_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Reject mostly non-printable / replacement-char garbage
    if cleaned:
        printable = sum(1 for c in cleaned[:500] if c.isprintable() or c.isspace())
        if printable / max(1, min(len(cleaned), 500)) < 0.85:
            return ""
    return cleaned[:_MAX_BODY]


def _crawl_with_playwright(url: str, storage_state: Optional[str]) -> list[dict]:
    """Fetch page content via Playwright; uses storage_state for login-walled sites."""
    if _looks_like_pdf(url):
        return _crawl_with_httpx(url)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed; falling back to httpx for %s", url)
        return _crawl_with_httpx(url)

    posts: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_kwargs: dict = {"user_agent": "VigilAI-Bot/1.0"}
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = page.title()
            body = _sanitize_text(page.inner_text("body") or "")
            if not body:
                return []
            posts.append({
                "external_id": f"playwright:{url}",
                "platform": "pathfinder",
                "url": url,
                "title": (title or url)[:500],
                "body": body,
                "region": "Global",
            })
        except Exception as exc:
            logger.warning("Playwright crawl failed for %s: %s", url, exc)
        finally:
            context.close()
            browser.close()
    return posts


def _crawl_with_httpx(url: str) -> list[dict]:
    import httpx

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "VigilAI-Bot/1.0"})
            if r.status_code >= 400:
                return []

            ctype = r.headers.get("content-type", "")
            raw = r.content or b""

            if _looks_like_pdf(url, ctype, raw[:16]):
                post = _extract_pdf_text(raw, url)
                return [post] if post else []

            # Avoid treating binary as HTML
            if "text/" not in ctype.lower() and "html" not in ctype.lower() and "xml" not in ctype.lower():
                if raw[:5] == b"%PDF-" or b"\x00" in raw[:500]:
                    return []

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = soup.title.string if soup.title else url
            body = _sanitize_text(soup.get_text(separator=" ", strip=True))
            if not body:
                return []
            return [{
                "external_id": f"httpx:{url}",
                "platform": "pathfinder",
                "url": url,
                "title": (title or url)[:500],
                "body": body,
                "region": "Global",
            }]
    except Exception as exc:
        logger.warning("httpx crawl failed for %s: %s", url, exc)
        return []


def approve_and_onboard(
    db: Session,
    source: SuggestedSource,
    storage_profile: Optional[str] = None,
) -> dict:
    """User-approved onboarding: crawl with Playwright (or httpx fallback) and ingest.

    Login-walled sources do NOT crack CAPTCHAs. They reuse an analyst-owned
    Playwright storage_state (cookies) captured after a legitimate manual login.
    We still attempt a public httpx pass first — many forums expose teaser text.
    """
    source.approval_status = "ingesting"
    db.commit()

    crawl_backend = "none"
    storage_state = None
    needs_login = source.access_status == "login_required"
    if needs_login:
        profile = storage_profile or source.storage_profile or "cookies"
        source.storage_profile = profile
        storage_state = _resolve_storage_state(profile)

    # 1) Always try public fetch first (teaser / partially open pages)
    posts = _crawl_with_httpx(source.url)
    crawl_backend = "httpx" if posts else "none"

    # 2) Headless browser without cookies (JS-rendered public content)
    if not posts and not _looks_like_pdf(source.url):
        posts = _crawl_with_playwright(source.url, None)
        if posts:
            crawl_backend = "playwright"

    # 3) Analyst session vault for true login walls
    if not posts and needs_login:
        if not storage_state:
            source.approval_status = "pending"
            db.commit()
            vault_hint = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "project_vault",
                "cookies.json",
            )
            return {
                "ok": False,
                "error": (
                    "Page is login-walled and no public text was available. "
                    "Save your own logged-in browser session (do not share passwords) with:\n"
                    "  playwright codegen --save-storage=project_vault/cookies.json <forum-url>\n"
                    f"Expected file: {vault_hint} or {_PROFILE_DIR}/cookies.json. "
                    "Then click Approve & Onboard again. CAPTCHA/paywall cracking is not supported."
                ),
                "ingested": 0,
            }
        posts = _crawl_with_playwright(source.url, storage_state)
        crawl_backend = "playwright+storage_state" if posts else "playwright+storage_state_empty"

    if not posts:
        source.approval_status = "pending"
        db.commit()
        hint = ""
        if _looks_like_pdf(source.url):
            hint = " (PDF — install pypdf or pick an HTML page instead)"
        elif needs_login:
            hint = " (login wall — refresh cookies.json after logging in manually)"
        return {"ok": False, "error": f"Crawl returned no usable text{hint}", "ingested": 0}

    for p in posts:
        p["project_id"] = source.project_id
        p["body"] = _sanitize_text(p.get("body") or "")
        if not p["body"]:
            source.approval_status = "pending"
            db.commit()
            return {"ok": False, "error": "Crawl body looked like binary/PDF garbage — not ingested", "ingested": 0}

    count = ingest_posts(db, posts, project_id=source.project_id)
    # Same as Fetch / other sources: rebuild signals & alerts for this project
    try:
        signal_stats = recompute_signals(
            db, use_fda=False, with_narrative=False, project_id=source.project_id,
        )
    except Exception as exc:
        logger.warning("Signal recompute after pathfinder onboard failed: %s", exc)
        signal_stats = {"signals": 0, "alerts": 0}

    source.approval_status = "approved"
    source.onboarded_at = datetime.utcnow()
    db.commit()

    return {
        "ok": True,
        "ingested": count,
        "url": source.url,
        "access_status": source.access_status,
        "storage_state_used": bool(storage_state),
        "crawl_backend": crawl_backend,
        "signals": signal_stats.get("signals", 0),
        "alerts": signal_stats.get("alerts", 0),
        "reports": signal_stats.get("reports", 0),
        "source": "pathfinder",
    }


def source_to_dict(source: SuggestedSource) -> dict:
    flags: list = []
    if source.access_flags_json:
        try:
            flags = json.loads(source.access_flags_json)
        except json.JSONDecodeError:
            pass
    if source.access_status == "login_required":
        emoji = "🟡"
        label = "Requires Login"
        reason = (
            "Auth/paywall friction detected: " + ", ".join(flags[:5])
            if flags
            else "Login wall markers found in DOM (wp-login / sign-in / 登录 / 注册)."
        )
    else:
        emoji = "🟢"
        label = "Public"
        reason = "Open crawl — no authentication friction markers in DOM screen."
    return {
        "id": source.id,
        "project_id": source.project_id,
        "url": source.url,
        "domain": source.domain,
        "title": source.title,
        "access_status": source.access_status,
        "access_emoji": emoji,
        "access_label": label,
        "access_reason": reason,
        "access_flags": flags,
        "approval_status": source.approval_status,
        "storage_profile": source.storage_profile,
        "onboarded_at": source.onboarded_at.isoformat() if source.onboarded_at else None,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }
