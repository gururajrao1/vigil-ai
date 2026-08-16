"""Biomedical embedding engine — SapBERT / BioBERT dense vectors.

Loads ``cambridgeltl/SapBERT-from-PubMedBERT-fulltext`` via ``transformers`` +
``torch`` when weights are available (or ``VIGILAI_ALLOW_EMBED_DOWNLOAD=1``).
Otherwise degrades to deterministic char-ngram vectors so Omni-Search and
MedDRA resolution stay offline-first with zero API-key dependency.

Cold-start: model download / weight load is lazy and logged; callers never block
the process event loop longer than one encode once the singleton is warm.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from typing import List, Optional, Sequence, Union

import numpy as np

LOGGER = logging.getLogger("vigilai.nlp.sapbert_encoder")

SAPBERT_MODEL_ID = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
BIOBERT_FALLBACK_ID = "pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb"
FALLBACK_DIM = 768  # match SapBERT hidden size for index compatibility
NGRAM_DIM = 768
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _allow_download() -> bool:
    return os.getenv("VIGILAI_ALLOW_EMBED_DOWNLOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return (matrix / norms).astype(np.float32)


def ngram_embedding(text: str, *, dim: int = NGRAM_DIM) -> np.ndarray:
    """Deterministic hashed char-ngram bag (SapBERT self-alignment surrogate)."""
    s = f"  {(text or '').lower().strip()}  "
    vec = np.zeros(dim, dtype=np.float32)
    if not s.strip():
        return vec
    for n in (2, 3, 4):
        for i in range(max(0, len(s) - n + 1)):
            gram = s[i : i + n]
            h = int(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).hexdigest(), 16) % dim
            vec[h] += 1.0
    for tok in _TOKEN_RE.findall(text or ""):
        h = int(
            hashlib.blake2b(f"tok:{tok.lower()}".encode("utf-8"), digest_size=8).hexdigest(),
            16,
        ) % dim
        vec[h] += 1.5
    return _l2_normalize(vec.reshape(1, -1))[0]


class SapBERTEncoder:
    """Encode clinical text to L2-normalized dense vectors (SapBERT or n-gram)."""

    def __init__(
        self,
        *,
        model_id: str = SAPBERT_MODEL_ID,
        max_length: int = 64,
        batch_size: int = 32,
        device: Optional[str] = None,
    ) -> None:
        self.model_id = model_id
        self.max_length = max_length
        self.batch_size = max(1, batch_size)
        self.backend: str = "uninitialized"
        self.dim: int = FALLBACK_DIM
        self.device_name: str = "cpu"
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._lock = threading.RLock()
        self._load_error: Optional[str] = None
        self._init_started_at: Optional[float] = None
        self._init_elapsed_ms: Optional[float] = None
        self._resolve_device(device)
        self._lazy_init()

    def _resolve_device(self, device: Optional[str]) -> None:
        if device:
            self.device_name = device
            return
        try:
            import torch

            self.device_name = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            self.device_name = "cpu"

    def _lazy_init(self) -> None:
        with self._lock:
            if self.backend != "uninitialized":
                return
            self._init_started_at = time.perf_counter()
            LOGGER.info(
                "SapBERTEncoder cold-start begin (model=%s, device=%s, allow_download=%s)",
                self.model_id,
                self.device_name,
                _allow_download(),
            )
            loaded = self._try_load_transformers(self.model_id, label="sapbert")
            if not loaded:
                loaded = self._try_load_transformers(BIOBERT_FALLBACK_ID, label="biobert")
            if not loaded:
                self.backend = "ngram"
                self.dim = NGRAM_DIM
                self._load_error = self._load_error or "transformers/torch unavailable"
                LOGGER.info(
                    "SapBERTEncoder using ngram fallback (dim=%d): %s",
                    self.dim,
                    self._load_error,
                )
            self._init_elapsed_ms = (time.perf_counter() - self._init_started_at) * 1000.0
            LOGGER.info(
                "SapBERTEncoder ready backend=%s dim=%d device=%s cold_start_ms=%.1f",
                self.backend,
                self.dim,
                self.device_name,
                self._init_elapsed_ms,
            )

    def _try_load_transformers(self, model_id: str, *, label: str) -> bool:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"import failed: {exc}"
            LOGGER.debug("transformers/torch import failed: %s", exc)
            return False

        local_only = not _allow_download()
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=local_only)
            model = AutoModel.from_pretrained(model_id, local_files_only=local_only)
            model.eval()
            model.to(self.device_name)
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model
            self.model_id = model_id
            self.backend = label
            self.dim = int(getattr(model.config, "hidden_size", FALLBACK_DIM))
            # Warm-up encode so first user query avoids tokenizer compile cost
            _ = self._encode_torch(["warmup"])
            return True
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"{model_id}: {exc}"
            LOGGER.warning(
                "Could not load %s (%s); trying next backend. Hint: set "
                "VIGILAI_ALLOW_EMBED_DOWNLOAD=1 once to cache HF weights.",
                model_id,
                exc,
            )
            return False

    def _mean_pool(self, last_hidden: "object", attention_mask: "object") -> "object":
        """Mean-pool token embeddings, ignoring padded positions."""
        torch = self._torch
        assert torch is not None
        mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
        summed = torch.sum(last_hidden * mask, dim=1)
        counts = torch.clamp(mask.sum(dim=1), min=1e-9)
        return summed / counts

    def _encode_torch(self, texts: Sequence[str]) -> np.ndarray:
        torch = self._torch
        assert torch is not None and self._tokenizer is not None and self._model is not None
        batches: List[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            chunk = list(texts[start : start + self.batch_size])
            encoded = self._tokenizer(
                chunk,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {k: v.to(self.device_name) for k, v in encoded.items()}
            with torch.no_grad():
                outputs = self._model(**encoded)
                pooled = self._mean_pool(outputs.last_hidden_state, encoded["attention_mask"])
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            batches.append(pooled.detach().cpu().numpy().astype(np.float32))
        return np.vstack(batches) if batches else np.zeros((0, self.dim), dtype=np.float32)

    def encode(self, texts: Union[str, Sequence[str]]) -> np.ndarray:
        """Encode one string or a batch. Returns shape ``(dim,)`` or ``(n, dim)``."""
        self._lazy_init()
        single = isinstance(texts, str)
        batch = [texts] if single else [str(t) for t in texts]
        if not batch:
            empty = np.zeros((0, self.dim), dtype=np.float32)
            return empty

        if self.backend in {"sapbert", "biobert"} and self._model is not None:
            try:
                with self._lock:
                    matrix = self._encode_torch(batch)
                matrix = _l2_normalize(matrix)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Torch encode failed (%s); ngram fallback for this batch", exc)
                matrix = np.vstack([ngram_embedding(t, dim=self.dim) for t in batch])
        else:
            matrix = np.vstack([ngram_embedding(t, dim=self.dim) for t in batch])

        return matrix[0] if single else matrix

    def get_embedding(self, text: str) -> np.ndarray:
        """Public single-text API — dense L2-normalized vector."""
        return np.asarray(self.encode(text), dtype=np.float32).reshape(-1)

    def get_embeddings(self, texts: Sequence[str]) -> np.ndarray:
        """Batch API with internal pooling / micro-batching."""
        return np.asarray(self.encode(list(texts)), dtype=np.float32)

    def status(self) -> dict:
        self._lazy_init()
        return {
            "backend": self.backend,
            "model_id": self.model_id,
            "device": self.device_name,
            "dim": self.dim,
            "batch_size": self.batch_size,
            "cold_start_ms": self._init_elapsed_ms,
            "load_error": self._load_error,
            "allow_download": _allow_download(),
        }


_ENCODER: Optional[SapBERTEncoder] = None
_ENCODER_LOCK = threading.Lock()


def get_sapbert_encoder(**kwargs) -> SapBERTEncoder:
    """Process-wide singleton — amortizes Hugging Face cold-start."""
    global _ENCODER
    with _ENCODER_LOCK:
        if _ENCODER is None:
            _ENCODER = SapBERTEncoder(**kwargs)
        return _ENCODER


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    va = np.asarray(a, dtype=np.float32).reshape(-1)
    vb = np.asarray(b, dtype=np.float32).reshape(-1)
    if va.shape != vb.shape or va.size == 0:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
