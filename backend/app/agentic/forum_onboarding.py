"""Agentic forum onboarding: point VigilAI at any forum URL and it proposes an
extraction configuration (which HTML containers hold posts, title/date/content
selectors, and sample extracted posts).

Resolution order (each degrades gracefully to the next):
  1. Firecrawl scrape (if FIRECRAWL_API_KEY set) for clean markdown/HTML.
  2. Direct HTTP fetch (httpx) + heuristic selector analysis (no key, offline-safe).
  3. LLM refinement of the proposed config (Ollama, if available).
  4. Deterministic template config when there is no network at all.

This mirrors the Algo-Pharma agentic onboarding but with a robust no-key fallback.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List

from .. import llm
from ..config import settings
from ..nlp.pii import scrub

_CANDIDATE_SELECTORS = [
    ("article", r"<article[\s>]"),
    (".post", r'class="[^"]*\bpost\b[^"]*"'),
    (".comment", r'class="[^"]*\bcomment\b[^"]*"'),
    (".message", r'class="[^"]*\bmessage\b[^"]*"'),
    (".topic", r'class="[^"]*\btopic\b[^"]*"'),
    (".thread", r'class="[^"]*\bthread\b[^"]*"'),
    ("li.reply", r'class="[^"]*\breply\b[^"]*"'),
    (".entry-content", r'class="[^"]*\bentry-content\b[^"]*"'),
]


def _fetch(url: str) -> Dict[str, str] | None:
    # Firecrawl (optional, needs key)
    if settings.firecrawl_api_key:
        try:  # pragma: no cover - network/key dependent
            import httpx

            r = httpx.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {settings.firecrawl_api_key}"},
                json={"url": url, "formats": ["html", "markdown"]},
                timeout=20.0,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                return {"html": data.get("html", ""), "method": "firecrawl"}
        except Exception:
            pass
    # Direct fetch (no key)
    try:
        import httpx

        r = httpx.get(url, timeout=10.0, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 VigilAI-Onboarder"})
        if r.status_code == 200:
            return {"html": r.text, "method": "http"}
    except Exception:
        return None
    return None


def _heuristic_config(html: str) -> Dict:
    counts = {}
    for name, pattern in _CANDIDATE_SELECTORS:
        counts[name] = len(re.findall(pattern, html, flags=re.IGNORECASE))
    ranked = Counter(counts).most_common()
    best = next((sel for sel, n in ranked if n >= 2), ranked[0][0] if ranked else "article")
    best_n = counts.get(best, 0)
    # crude sample extraction: strip tags from a few candidate blocks
    samples = _sample_posts(html, best)
    confidence = min(0.95, 0.35 + 0.1 * min(best_n, 6))
    return {
        "post_selector": best,
        "title_selector": "h1, h2, .title, .subject",
        "date_selector": "time, .date, .posted",
        "content_selector": f"{best} .content, {best} p",
        "detected_counts": counts,
        "estimated_posts_per_page": best_n,
        "sample_posts": samples,
        "confidence": round(confidence, 2),
    }


def _sample_posts(html: str, selector: str, limit: int = 3) -> List[dict]:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    # split on paragraph-ish boundaries and keep substantial text blocks
    blocks = re.split(r"(?i)</p>|</div>|</article>|</li>", text)
    out = []
    for b in blocks:
        clean = re.sub(r"<[^>]+>", " ", b)
        clean = re.sub(r"\s+", " ", clean).strip()
        if 60 <= len(clean) <= 500:
            scrubbed, _ = scrub(clean)
            out.append({"content": scrubbed[:400]})
        if len(out) >= limit:
            break
    return out


def _template_config() -> Dict:
    return {
        "post_selector": ".post",
        "title_selector": "h1, h2, .title",
        "date_selector": "time, .date",
        "content_selector": ".post .content, .post p",
        "detected_counts": {},
        "estimated_posts_per_page": 0,
        "sample_posts": [],
        "confidence": 0.2,
    }


def onboard_forum(url: str) -> Dict:
    """Analyze a forum URL and return a proposed extraction config."""
    fetched = _fetch(url)
    if not fetched or not fetched.get("html"):
        cfg = _template_config()
        cfg.update({"forum_url": url, "method": "template_offline",
                    "forum_type": "unknown", "note": "URL unreachable; returning template"})
        return cfg

    cfg = _heuristic_config(fetched["html"])
    cfg["method"] = fetched["method"]
    cfg["forum_url"] = url

    # Detect a rough forum type from the HTML
    html_low = fetched["html"].lower()
    if "wp-content" in html_low or "wordpress" in html_low:
        cfg["forum_type"] = "wordpress"
    elif "discourse" in html_low:
        cfg["forum_type"] = "discourse"
    elif "phpbb" in html_low:
        cfg["forum_type"] = "phpbb"
    elif "reddit" in html_low:
        cfg["forum_type"] = "reddit"
    else:
        cfg["forum_type"] = "generic"

    # Optional LLM refinement (does not block; only augments) — Ollama → Gemini → OpenRouter
    if settings.use_llm and (llm.ollama_available() or settings.gemini_api_key or settings.openrouter_api_key):
        refined = llm.generate_json(
            "Given these detected HTML container counts from a patient forum, return "
            "JSON with the best CSS selectors to extract individual posts. Keys: "
            "post_selector, title_selector, date_selector, content_selector. "
            f"Counts: {cfg['detected_counts']}",
            system="You are a web-scraping expert. JSON only.",
            temperature=0.1,
        )
        if isinstance(refined, dict) and refined.get("post_selector"):
            cfg["llm_suggested"] = refined
            cfg["confidence"] = min(0.98, cfg["confidence"] + 0.1)

    return cfg
