"""Step 2 — FAISS / dense k-NN UMLS linker + MedNorm/BERGAMOT dual map.

Precomputes SapBERT (or n-gram) embeddings for the UMLS-style concept catalog,
indexes them with FAISS IndexFlatIP (cosine via L2-normalized vectors), and
returns top-k CUI hits with simultaneous MedDRA PT + SNOMED-CT codes.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from . import catalog
from .models import CandidateHit, ConceptLink, EmbeddingTrace
from .sapbert_encoder import get_encoder

logger = logging.getLogger("vigilai.mcn.umls_linker")

COSINE_THRESHOLD = 0.42
NGRAM_COSINE_THRESHOLD = 0.78
FUZZY_THRESHOLD = 78.0


class UmlsLinker:
    """Dense retrieval linker over the surrogate Metathesaurus catalog."""

    def __init__(self) -> None:
        self.surfaces = catalog.concept_surfaces()  # (surface, concept)
        self.encoder = get_encoder()
        self.backend = self.encoder.backend
        self.faiss_enabled = False
        self._index = None
        self._matrix: Optional[np.ndarray] = None
        self._concepts: List[dict] = [c for _, c in self.surfaces]
        self._surface_keys: List[str] = [s for s, _ in self.surfaces]
        self._alias_index = {s: c for s, c in self.surfaces}
        self._build_index()

    def _build_index(self) -> None:
        if not self._surface_keys:
            self._matrix = np.zeros((0, self.encoder.dim), dtype=np.float32)
            return
        matrix = self.encoder.encode(self._surface_keys)
        self._matrix = np.asarray(matrix, dtype=np.float32)
        self.backend = self.encoder.backend
        try:
            import faiss  # type: ignore

            dim = self._matrix.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(self._matrix)
            self._index = index
            self.faiss_enabled = True
            self.backend = f"{self.backend}+faiss"
            logger.info("MCN FAISS IndexFlatIP ready (%s vectors, dim=%s)", len(self._surface_keys), dim)
        except Exception as exc:
            self._index = None
            self.faiss_enabled = False
            logger.info("MCN FAISS unavailable (%s); using numpy cosine", exc)

    def _exact(self, query: str) -> Optional[Tuple[dict, str, float]]:
        key = (query or "").strip().lower()
        concept = self._alias_index.get(key)
        if concept:
            return concept, key, 1.0
        return None

    def _fuzzy(self, query: str) -> Optional[Tuple[dict, str, float]]:
        q = (query or "").strip().lower()
        if not q:
            return None
        try:
            from rapidfuzz import fuzz, process

            hit = process.extractOne(
                q,
                self._surface_keys,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=FUZZY_THRESHOLD,
            )
            if not hit:
                return None
            surface, score, _idx = hit
            return self._alias_index[surface], surface, float(score) / 100.0
        except Exception:
            from difflib import SequenceMatcher

            best_s, best_c, best = "", None, 0.0
            for surface, concept in self.surfaces:
                ratio = SequenceMatcher(None, q, surface).ratio()
                if ratio > best:
                    best, best_s, best_c = ratio, surface, concept
            if best_c and best * 100 >= FUZZY_THRESHOLD:
                return best_c, best_s, best
            return None

    def _dense_topk(self, query: str, k: int = 5) -> List[Tuple[int, float]]:
        if self._matrix is None or self._matrix.shape[0] == 0:
            return []
        qv = np.asarray(self.encoder.encode(query), dtype=np.float32).reshape(1, -1)
        if self._index is not None:
            scores, idxs = self._index.search(qv, min(k, self._matrix.shape[0]))
            out: List[Tuple[int, float]] = []
            for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
                if idx < 0:
                    continue
                out.append((int(idx), float(score)))
            return out
        sims = (self._matrix @ qv.T).reshape(-1)
        order = np.argsort(-sims)[:k]
        return [(int(i), float(sims[i])) for i in order]

    def link(self, verbatim: str, *, top_k: int = 5) -> ConceptLink:
        text = (verbatim or "").strip()
        emb = EmbeddingTrace(**self.encoder.trace(text))
        if not text:
            return ConceptLink(verbatim=text or "", embedding=emb)

        exact = self._exact(text)
        if exact:
            concept, surface, score = exact
            return self._pack(text, concept, surface, score, "exact_alias", emb, top_k=top_k)

        fuzzy = self._fuzzy(text)
        if fuzzy:
            concept, surface, score = fuzzy
            # Prefer fuzzy when high confidence; still attach dense neighbours for trace
            return self._pack(text, concept, surface, score, "fuzzy_alias", emb, top_k=top_k)

        dense = self._dense_topk(text, k=max(top_k, 1))
        if not dense:
            return ConceptLink(verbatim=text, embedding=emb, match_method="unmatched")

        idx, cosine = dense[0]
        threshold = (
            NGRAM_COSINE_THRESHOLD
            if "ngram" in (self.encoder.backend or "")
            else COSINE_THRESHOLD
        )
        if cosine < threshold:
            hits = self._hits_from_dense(dense)
            return ConceptLink(
                verbatim=text,
                embedding=emb,
                match_method="dense_below_threshold",
                cosine=round(cosine, 4),
                top_k=hits,
            )

        concept = self._concepts[idx]
        surface = self._surface_keys[idx]
        return self._pack(
            text,
            concept,
            surface,
            cosine,
            "faiss_cosine" if self.faiss_enabled else "numpy_cosine",
            emb,
            top_k=top_k,
            dense=dense,
        )

    def _hits_from_dense(self, dense: List[Tuple[int, float]]) -> List[CandidateHit]:
        hits: List[CandidateHit] = []
        for rank, (idx, score) in enumerate(dense, start=1):
            concept = self._concepts[idx]
            hits.append(
                CandidateHit(
                    cui=concept["cui"],
                    preferred=concept["preferred"],
                    meddra_pt=concept.get("meddra_pt"),
                    snomed_ct=concept.get("snomed_ct"),
                    matched_surface=self._surface_keys[idx],
                    cosine=round(float(score), 4),
                    rank=rank,
                )
            )
        return hits

    def _pack(
        self,
        verbatim: str,
        concept: dict,
        surface: str,
        score: float,
        method: str,
        emb: EmbeddingTrace,
        *,
        top_k: int,
        dense: Optional[List[Tuple[int, float]]] = None,
    ) -> ConceptLink:
        dense = dense or self._dense_topk(verbatim, k=top_k)
        hits = self._hits_from_dense(dense)
        # Ensure the chosen concept appears as rank-1 in the trace
        if not hits or hits[0].cui != concept["cui"]:
            hits = [
                CandidateHit(
                    cui=concept["cui"],
                    preferred=concept["preferred"],
                    meddra_pt=concept.get("meddra_pt"),
                    snomed_ct=concept.get("snomed_ct"),
                    matched_surface=surface,
                    cosine=round(float(score), 4),
                    rank=1,
                ),
                *[h.model_copy(update={"rank": i + 2}) for i, h in enumerate(hits[: top_k - 1])],
            ]
        return ConceptLink(
            verbatim=verbatim,
            matched=True,
            cui=concept["cui"],
            preferred=concept["preferred"],
            meddra_pt=concept.get("meddra_pt"),
            snomed_ct=concept.get("snomed_ct"),
            kind=concept.get("kind"),
            match_method=method,
            cosine=round(float(score), 4),
            embedding=emb,
            top_k=hits[:top_k],
        )


_LINKER: Optional[UmlsLinker] = None


def get_linker() -> UmlsLinker:
    global _LINKER
    if _LINKER is None:
        _LINKER = UmlsLinker()
    return _LINKER


def link_to_umls(verbatim: str, *, top_k: int = 5) -> ConceptLink:
    return get_linker().link(verbatim, top_k=top_k)
