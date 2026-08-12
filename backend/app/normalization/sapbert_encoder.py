"""Step 1 — SapBERT (or offline char-ngram) dense embeddings for MCN spans.

Uses ``cambridgeltl/SapBERT-from-PubMedBERT-fulltext`` when local Hugging Face
weights are present (or ``VIGILAI_ALLOW_EMBED_DOWNLOAD=1``). Otherwise falls
back to deterministic 64-d char-ngram vectors so MCN stays offline-first.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import List, Optional, Sequence, Union

import numpy as np

logger = logging.getLogger("vigilai.mcn.sapbert")

SAPBERT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
FALLBACK_DIM = 64
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


class SapBertEncoder:
    """Encode entity spans into L2-normalized dense vectors."""

    def __init__(self, *, dim: int = FALLBACK_DIM) -> None:
        self.dim = dim
        self.backend = "ngram"
        self._model = None
        self._encode_fn = None
        self._init_encoder()

    def _init_encoder(self) -> None:
        allow_download = os.getenv("VIGILAI_ALLOW_EMBED_DOWNLOAD", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        for model_name, label in (
            (SAPBERT_MODEL, "sapbert"),
            ("pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb", "biobert"),
            ("sentence-transformers/all-MiniLM-L6-v2", "minilm"),
        ):
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(model_name, local_files_only=not allow_download)
                self._model = model
                self._encode_fn = lambda texts, m=model: np.asarray(
                    m.encode(list(texts), normalize_embeddings=True, show_progress_bar=False),
                    dtype=np.float32,
                )
                self.backend = label
                # SapBERT / MiniLM are typically 768-d; expose actual dim after first encode
                probe = self._encode_fn(["probe"])
                self.dim = int(probe.shape[1])
                logger.info("MCN SapBERT encoder backend: %s (dim=%s)", label, self.dim)
                return
            except Exception as exc:
                logger.debug("MCN encoder %s unavailable: %s", label, exc)

        self._encode_fn = None
        self.backend = "ngram"
        self.dim = FALLBACK_DIM
        logger.info("MCN SapBERT encoder backend: ngram fallback (dim=%s)", self.dim)

    @staticmethod
    def _ngram_vec(text: str, dim: int = FALLBACK_DIM) -> np.ndarray:
        """Deterministic hashed char-ngram bag — SapBERT self-alignment surrogate."""
        s = f"  {(text or '').lower().strip()}  "
        vec = np.zeros(dim, dtype=np.float32)
        if not s.strip():
            return vec
        for n in (2, 3, 4):
            for i in range(max(0, len(s) - n + 1)):
                gram = s[i : i + n]
                h = hash(gram) % dim
                vec[h] += 1.0
        for tok in _TOKEN_RE.findall(text or ""):
            h = hash(f"tok:{tok.lower()}") % dim
            vec[h] += 1.5
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def encode(self, texts: Union[str, Sequence[str]]) -> np.ndarray:
        if isinstance(texts, str):
            batch = [texts]
            single = True
        else:
            batch = list(texts)
            single = False
        if not batch:
            empty = np.zeros((0, self.dim), dtype=np.float32)
            return empty

        if self._encode_fn is not None:
            try:
                matrix = self._encode_fn(batch)
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                matrix = (matrix / norms).astype(np.float32)
            except Exception as exc:
                logger.warning("SapBERT encode failed (%s); using ngram", exc)
                matrix = np.vstack([self._ngram_vec(t, self.dim) for t in batch])
                self.backend = "ngram"
        else:
            matrix = np.vstack([self._ngram_vec(t, self.dim) for t in batch])

        return matrix[0] if single else matrix

    def trace(self, text: str, *, preview: int = 8) -> dict:
        vec = self.encode(text)
        arr = np.asarray(vec, dtype=np.float32).reshape(-1)
        return {
            "verbatim": text,
            "vector_dim": int(arr.shape[0]),
            "encoder_backend": self.backend,
            "vector_preview": [round(float(x), 5) for x in arr[:preview].tolist()],
            "l2_norm": round(float(np.linalg.norm(arr)), 5),
        }


_ENCODER: Optional[SapBertEncoder] = None


def get_encoder() -> SapBertEncoder:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = SapBertEncoder()
    return _ENCODER


def encode_span(text: str) -> np.ndarray:
    """Public embedding function for extracted entity spans."""
    return get_encoder().encode(text)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    va = np.asarray(a, dtype=np.float32).reshape(-1)
    vb = np.asarray(b, dtype=np.float32).reshape(-1)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
