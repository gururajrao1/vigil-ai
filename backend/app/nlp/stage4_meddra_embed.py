"""Stage 4 — Layman-to-MedDRA semantic mapping.

Maps loose patient-voice complaints to MedDRA-style Preferred Terms via vector
cosine similarity (threshold 0.85). Prefers local all-MiniLM-L6-v2 when
sentence-transformers is installed; otherwise uses a deterministic character
n-gram embedding (offline, zero extra deps beyond numpy).
"""
from __future__ import annotations

import logging
import math
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from .stage1_sanitize import fold_key, sanitize_surface
from .stage2_synonyms import lookup_event_synonym

logger = logging.getLogger("vigilai.meddra_embed")

SIMILARITY_THRESHOLD = 0.85

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)

# Extra layman phrases not already covered by synonym registry / PT map keys
_LAYMAN_HINTS: dict[str, str] = {
    "brain zaps": "paresthesia",
    "electric shocks in head": "paresthesia",
    "pins and needles": "tingling",
    "stomach bug feeling": "nausea",
    "throwing up": "vomiting",
    "can't sleep": "insomnia",
    "heart racing": "palpitations",
    "out of breath": "shortness of breath",
    "face blew up": "swollen face",
    "broke out in hives": "hives",
}


def _pt_catalog() -> List[Tuple[str, str, str]]:
    """Return list of (surface_for_embed, preferred_term, soc_code)."""
    from .meddra import SOC, _PT_MAP

    rows: List[Tuple[str, str, str]] = []
    seen = set()
    for surface, (pt, soc_key) in _PT_MAP.items():
        rows.append((surface, pt, soc_key))
        if pt.lower() not in seen:
            rows.append((pt.lower(), pt, soc_key))
            seen.add(pt.lower())
    for phrase, pt in _LAYMAN_HINTS.items():
        # Resolve SOC via map_term when possible
        from .meddra import map_term

        md = map_term(pt)
        rows.append((phrase, md["pt"], md["soc_code"]))
    return rows


def _char_ngrams(text: str, n: int = 3) -> Dict[str, float]:
    s = f"  {fold_key(text).lower()}  "
    if len(s) < n:
        return {s: 1.0}
    counts: Dict[str, float] = {}
    for i in range(len(s) - n + 1):
        g = s[i : i + n]
        counts[g] = counts.get(g, 0.0) + 1.0
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def _cosine_sparse(a: Dict[str, float], b: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


class _NgramIndex:
    """Deterministic offline embedding index over MedDRA surrogate PTs."""

    def __init__(self) -> None:
        self.catalog = _pt_catalog()
        self.vectors = [_char_ngrams(surface) for surface, _, _ in self.catalog]

    def query(self, text: str, threshold: float = SIMILARITY_THRESHOLD) -> Optional[dict]:
        q = _char_ngrams(text)
        best_i, best_score = -1, 0.0
        for i, vec in enumerate(self.vectors):
            score = _cosine_sparse(q, vec)
            if score > best_score:
                best_i, best_score = i, score
        if best_i < 0 or best_score < threshold:
            return None
        surface, pt, soc_key = self.catalog[best_i]
        from .meddra import SOC

        return {
            "pt": pt,
            "soc_code": soc_key,
            "soc": SOC.get(soc_key, SOC["GEN"]),
            "matched": True,
            "similarity": round(best_score, 4),
            "method": "ngram_cosine",
            "matched_surface": surface,
        }


class _MiniLMIndex:
    """Optional sentence-transformers all-MiniLM-L6-v2 index."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.catalog = _pt_catalog()
        self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        texts = [s for s, _, _ in self.catalog]
        self.matrix = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    def query(self, text: str, threshold: float = SIMILARITY_THRESHOLD) -> Optional[dict]:
        vec = self.model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
        scores = np.dot(self.matrix, vec)
        best_i = int(np.argmax(scores))
        best_score = float(scores[best_i])
        if best_score < threshold:
            return None
        surface, pt, soc_key = self.catalog[best_i]
        from .meddra import SOC

        return {
            "pt": pt,
            "soc_code": soc_key,
            "soc": SOC.get(soc_key, SOC["GEN"]),
            "matched": True,
            "similarity": round(best_score, 4),
            "method": "minilm_cosine",
            "matched_surface": surface,
        }


_INDEX = None
_INDEX_KIND = "none"


def _get_index():
    global _INDEX, _INDEX_KIND
    if _INDEX is not None:
        return _INDEX
    try:
        _INDEX = _MiniLMIndex()
        _INDEX_KIND = "minilm"
        logger.info("MedDRA embed index: all-MiniLM-L6-v2")
    except Exception as exc:
        logger.info("MedDRA embed index: n-gram fallback (%s)", exc)
        _INDEX = _NgramIndex()
        _INDEX_KIND = "ngram"
    return _INDEX


def embed_backend() -> str:
    _get_index()
    return _INDEX_KIND


def map_layman_to_meddra(
    surface: str, *, threshold: float = SIMILARITY_THRESHOLD
) -> Optional[dict]:
    """Map a patient-voice phrase to a MedDRA-style PT via cosine ≥ threshold."""
    cleaned = sanitize_surface(surface).cleaned
    if not cleaned:
        return None

    syn = lookup_event_synonym(cleaned)
    if syn:
        from .meddra import map_term

        md = map_term(syn)
        if md.get("matched"):
            return {
                **md,
                "similarity": 1.0,
                "method": "synonym",
                "matched_surface": syn,
            }

    # Exact / dict path first (cheaper than vectors)
    from .meddra import map_term

    exact = map_term(cleaned.lower())
    if exact.get("matched"):
        return {
            **exact,
            "similarity": 1.0,
            "method": "exact",
            "matched_surface": cleaned.lower(),
        }

    hint_key = cleaned.lower()
    if hint_key in _LAYMAN_HINTS:
        md = map_term(_LAYMAN_HINTS[hint_key])
        return {
            **md,
            "similarity": 1.0,
            "method": "layman_hint",
            "matched_surface": hint_key,
        }

    return _get_index().query(cleaned, threshold=threshold)
