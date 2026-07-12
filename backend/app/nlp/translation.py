"""Worldwide language detection + translation to English.

Detects the source language of a post (any language) and translates it to English
so the downstream NLP works globally. Uses:

1. langdetect for detection (offline, ~55 languages).
2. deep-translator (Google backend, no API key) for translation when online.

Everything degrades gracefully: if detection or translation libs are missing, or
there is no network, the original text is returned unchanged and marked so the
pipeline keeps working fully offline.
"""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Dict

from ..config import settings

logger = logging.getLogger("vigilai.translation")

# Bounded executor + cache so a slow/blocked translation endpoint can never hang
# the ingest pipeline. Repeated strings (common in demos) are served from cache.
_EXECUTOR = ThreadPoolExecutor(max_workers=2)
_CACHE: Dict[str, str] = {}
_CACHE_LOCK = threading.Lock()
_TRANSLATE_TIMEOUT = 6.0

# ISO code -> human name (subset spanning major world + Indian languages).
LANG_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian",
    "zh-cn": "Chinese", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    "ar": "Arabic", "tr": "Turkish", "vi": "Vietnamese", "th": "Thai",
    "id": "Indonesian", "pl": "Polish", "uk": "Ukrainian", "fa": "Persian",
    "hi": "Hindi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
    "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
    "pa": "Punjabi", "ur": "Urdu", "or": "Odia",
}

_ASCII_RE = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str:
    """Return a best-effort ISO language code; 'en' as safe default."""
    if not text or len(text.strip()) < 8:
        return "en"
    try:
        from langdetect import detect  # type: ignore

        code = detect(text)
        return code.lower()
    except Exception:
        # Heuristic: mostly-ASCII -> assume English.
        letters = _ASCII_RE.findall(text)
        return "en" if len(letters) >= max(3, len(text) * 0.5) else "unknown"


def _do_translate(text: str) -> str:
    from deep_translator import GoogleTranslator  # type: ignore

    return GoogleTranslator(source="auto", target="en").translate(text[:4500])


def translate_to_english(text: str, src: str | None = None,
                         online: bool | None = None) -> Dict[str, str]:
    """Return {text, lang, translated(bool), lang_name}.

    Language is always detected/labelled (worldwide), even when translation is
    skipped, so dashboards still show global language coverage.

    ``online`` controls the network translation call:
      * None  -> follow the ``USE_ONLINE_TRANSLATION`` setting.
      * True  -> translate via the free Google backend (bounded by a hard timeout).
      * False -> skip the network call (used for fast bulk ingest); the original
                 text is kept but the detected language is still recorded.
    The network call is wrapped in a hard timeout and cache so it can never hang.
    """
    if not text:
        return {"text": "", "lang": "en", "translated": False, "lang_name": "English"}

    lang = (src or detect_language(text)).lower()
    name = LANG_NAMES.get(lang, lang or "unknown")

    if lang in {"en", "unknown", ""}:
        return {"text": text, "lang": "en" if lang in {"en", ""} else lang,
                "translated": False, "lang_name": LANG_NAMES.get(lang, "English")}

    do_online = settings.use_online_translation if online is None else online
    if not do_online:
        return {"text": text, "lang": lang, "translated": False, "lang_name": name}

    with _CACHE_LOCK:
        if text in _CACHE:
            return {"text": _CACHE[text], "lang": lang, "translated": True, "lang_name": name}

    try:
        out = _EXECUTOR.submit(_do_translate, text).result(timeout=_TRANSLATE_TIMEOUT)
        if out and out.strip():
            with _CACHE_LOCK:
                _CACHE[text] = out
            return {"text": out, "lang": lang, "translated": True, "lang_name": name}
    except FutureTimeout:
        logger.warning("Translation timed out (%s); keeping original text.", lang)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("Translation failed (%s): %s", lang, exc)

    return {"text": text, "lang": lang, "translated": False, "lang_name": name}
