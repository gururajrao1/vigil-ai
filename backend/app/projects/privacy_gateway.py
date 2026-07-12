"""Step 4 — async Presidio privacy gateway before 4-gate NLP extraction."""
from __future__ import annotations

import asyncio
import logging
from typing import List, Tuple

from ..config import settings
from ..nlp.pii import scrub

logger = logging.getLogger("vigilai.privacy_gateway")


def pii_mode(use_presidio: bool | None = None) -> str:
    """Return active scrubbing mode: presidio+regex or regex_only."""
    if use_presidio is False:
        return "regex_only"
    if not settings.use_presidio:
        return "regex_only"
    from ..nlp.pii import _presidio
    analyzer, _ = _presidio()
    return "presidio+regex" if analyzer else "regex_only"


async def scrub_async(
    text: str,
    *,
    use_presidio: bool | None = None,
) -> Tuple[str, List[str]]:
    """Run layered PII scrubbing off the event loop (Presidio is CPU-bound).

    This is the mandatory gateway immediately before Product → Symptom →
    Sentiment → Negation NLP. Regex layer always runs; Presidio follows
    ``USE_PRESIDIO`` unless explicitly overridden.
    """
    if not text:
        return "", []

    presidio = settings.use_presidio if use_presidio is None else use_presidio
    # scrub() always runs regex; Presidio is optional and skipped silently when unavailable
    if presidio is False:
        return await asyncio.to_thread(scrub, text, False)
    return await asyncio.to_thread(scrub, text, None)


async def scrub_batch(
    texts: List[str],
    *,
    use_presidio: bool | None = None,
) -> List[Tuple[str, List[str]]]:
    """Scrub multiple payloads concurrently (bounded parallelism)."""
    sem = asyncio.Semaphore(4)

    async def _one(t: str) -> Tuple[str, List[str]]:
        async with sem:
            return await scrub_async(t, use_presidio=use_presidio)

    return await asyncio.gather(*[_one(t) for t in texts])


def scrub_sync(
    text: str,
    *,
    use_presidio: bool | None = None,
) -> Tuple[str, List[str]]:
    """Synchronous entrypoint for the privacy gateway (used by ingest pipeline)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(scrub_async(text, use_presidio=use_presidio))
    return scrub(text, use_presidio=use_presidio)


def scrub_sync_with_meta(
    text: str,
    *,
    use_presidio: bool | None = None,
) -> Tuple[str, List[str], str]:
    """Like scrub_sync but returns the active mode for audit/UI surfaces."""
    cleaned, types = scrub_sync(text, use_presidio=use_presidio)
    return cleaned, types, pii_mode(use_presidio)
