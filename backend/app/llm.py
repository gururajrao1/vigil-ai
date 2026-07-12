"""Unified LLM client. Local-first (Ollama, no key), with graceful cloud fallbacks.

Priority: Ollama (local) → Gemini Flash (free key) → OpenRouter (paid key) → None.

Callers must always handle a None/empty return by using a deterministic fallback
so the whole product works offline with zero API keys.

For deployed users who don't have Ollama:
  - Set GEMINI_API_KEY in environment (free at aistudio.google.com)
  - Uses gemini-2.0-flash-lite — free tier, no billing required
  - Falls back to deterministic text if no key configured
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from .config import settings

logger = logging.getLogger("vigilai.llm")

_OLLAMA_OK: Optional[bool] = None

# Gemini free models — try in order, first success wins
_GEMINI_MODELS = [
    "gemini-2.5-flash-lite",   # latest free lite
    "gemini-2.5-flash",        # slightly heavier but still free
    "gemini-2.0-flash-lite",   # previous gen lite
]
_GEMINI_MODEL = _GEMINI_MODELS[0]  # reported in status
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def ollama_available() -> bool:
    """Cheap health check of the local Ollama daemon (cached per process)."""
    global _OLLAMA_OK
    if _OLLAMA_OK is not None:
        return _OLLAMA_OK
    if not (settings.use_llm and settings.ollama_base_url):
        _OLLAMA_OK = False
        return False
    try:
        import httpx
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2.0)
        _OLLAMA_OK = r.status_code == 200
    except Exception:
        _OLLAMA_OK = False
    return _OLLAMA_OK


def reset_health() -> None:
    global _OLLAMA_OK
    _OLLAMA_OK = None


def active_backend() -> str:
    """Which LLM backend will be used. Used for status display."""
    if not settings.use_llm:
        return "disabled"
    if ollama_available():
        return f"ollama/{settings.ollama_model}"
    if settings.gemini_api_key:
        return f"gemini/{_GEMINI_MODEL}"
    if settings.openrouter_api_key:
        return "openrouter"
    return "deterministic"


def _ollama_generate(prompt: str, system: str, temperature: float, want_json: bool) -> Optional[str]:
    try:
        import httpx
        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if want_json:
            payload["format"] = "json"
        r = httpx.post(f"{settings.ollama_base_url}/api/generate", json=payload, timeout=60.0)
        if r.status_code == 200:
            return (r.json().get("response") or "").strip()
    except Exception as exc:
        logger.debug("Ollama generate failed: %s", exc)
    return None


def _gemini_generate(prompt: str, system: str, temperature: float, want_json: bool) -> Optional[str]:
    """Call Google Gemini REST API directly (no SDK dependency).

    Tries each model in _GEMINI_MODELS in order; skips on 429/404, returns on
    first success. 429 means rate-limited on that model — try the next one.
    """
    if not settings.gemini_api_key:
        return None
    try:
        import httpx
        combined = f"[System: {system}]\n\n{prompt}" if system else prompt
        contents = [{"role": "user", "parts": [{"text": combined}]}]
        body: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 1024},
        }
        if want_json:
            body["generationConfig"]["responseMimeType"] = "application/json"

        for model in _GEMINI_MODELS:
            url = f"{_GEMINI_BASE}/models/{model}:generateContent?key={settings.gemini_api_key}"
            try:
                r = httpx.post(url, json=body, timeout=30.0)
                if r.status_code == 200:
                    candidates = r.json().get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "").strip()
                            if text:
                                return text
                elif r.status_code in (429, 404, 503):
                    # rate-limited or model unavailable — try next model
                    logger.debug("Gemini %s %s, trying next model", model, r.status_code)
                    continue
                else:
                    logger.debug("Gemini %s error %s: %s", model, r.status_code, r.text[:120])
            except Exception as exc:
                logger.debug("Gemini %s request failed: %s", model, exc)
    except Exception as exc:
        logger.debug("Gemini generate failed: %s", exc)
    return None


def _openai_compatible(base_url: str, api_key: str, model: str, prompt: str,
                       system: str, temperature: float, want_json: bool) -> Optional[str]:
    try:
        import httpx
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        if want_json:
            body["response_format"] = {"type": "json_object"}
        r = httpx.post(
            f"{base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.debug("OpenAI-compatible LLM failed: %s", exc)
    return None


def generate(prompt: str, system: str = "You are a helpful assistant.",
             temperature: float = 0.2, want_json: bool = False) -> Optional[str]:
    """Return raw model text, or None if no backend is available.

    Fallback chain: Ollama → Gemini (free) → OpenRouter → None.
    Callers must always handle None with deterministic output.
    """
    if not settings.use_llm:
        return None

    # 1. Local Ollama (no key, best for privacy)
    if ollama_available():
        out = _ollama_generate(prompt, system, temperature, want_json)
        if out:
            return out

    # 2. Google Gemini (free tier — set GEMINI_API_KEY, no billing required)
    if settings.gemini_api_key:
        out = _gemini_generate(prompt, system, temperature, want_json)
        if out:
            return out

    # 3. OpenRouter (paid, many model options)
    if settings.openrouter_api_key:
        model = (settings.ollama_model if "/" in settings.ollama_model
                 else "openai/gpt-4o-mini")
        out = _openai_compatible(settings.openrouter_base_url, settings.openrouter_api_key,
                                 model, prompt, system, temperature, want_json)
        if out:
            return out

    return None  # callers use deterministic fallback


def generate_json(prompt: str, system: str = "Respond with strict JSON only.",
                  temperature: float = 0.2) -> Optional[dict]:
    """Return parsed JSON dict from the model, or None."""
    raw = generate(prompt, system=system, temperature=temperature, want_json=True)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
    return None


def status() -> dict:
    backend = active_backend()
    return {
        "use_llm": settings.use_llm,
        "backend": backend,
        "ollama": ollama_available(),
        "ollama_model": settings.ollama_model,
        "gemini": bool(settings.gemini_api_key),
        "gemini_model": _GEMINI_MODEL if settings.gemini_api_key else None,
        "openrouter": bool(settings.openrouter_api_key),
        "note": (
            "Add GEMINI_API_KEY for free cloud LLM (aistudio.google.com)"
            if backend == "deterministic" and settings.use_llm
            else None
        ),
    }
