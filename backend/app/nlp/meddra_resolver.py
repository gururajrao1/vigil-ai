"""MedDRA / symptom normalizer — colloquial AE → PT / SOC via SapBERT + FAISS.

Maps free-text symptoms (including vernacular like ``brain fog``, ``upset stomach``,
``shaky hands``) onto open MedDRA-surrogate Preferred Terms using:

1. Vernacular + exact lexicon hits
2. Cosine similarity over SapBERT (or n-gram) embeddings of MedDRA concept names
3. Optional FAISS ANN index when ``faiss`` is installed

Returns OMOP ``concept_id`` when ``omop_concept`` holds MedDRA rows; otherwise a
stable surrogate id derived from the PT code.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .sapbert_encoder import SapBERTEncoder, get_sapbert_encoder

LOGGER = logging.getLogger("vigilai.nlp.meddra_resolver")

CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "nlp_cache"
EMBED_CACHE = CACHE_DIR / "meddra_sapbert_index.npz"


class MedDRAResolution(BaseModel):
    """Structured Omni-Search adverse-event payload."""

    query: str
    matched: bool = False
    match_method: str = "unmatched"
    concept_id: Optional[int] = None
    concept_name: Optional[str] = None
    meddra_code: Optional[str] = None
    preferred_term: Optional[str] = None
    soc: Optional[str] = None
    soc_code: Optional[str] = None
    similarity: float = Field(0.0, description="Cosine / confidence score in [0, 1]")
    confidence: float = 0.0
    vernacular_canonical: Optional[str] = None
    candidates: List[dict] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


def _stable_id(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _to_async_url(raw: str) -> str:
    url = make_url(raw.strip())
    driver = (url.drivername or "").lower()
    if "asyncpg" in driver:
        return url.render_as_string(hide_password=False)
    if driver in {"postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"}:
        return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    if driver.startswith("sqlite"):
        if "aiosqlite" not in driver:
            return url.set(drivername="sqlite+aiosqlite").render_as_string(hide_password=False)
        return url.render_as_string(hide_password=False)
    raise ValueError(f"Unsupported DATABASE_URL dialect: {driver!r}")


class _MedDRAIndex:
    """In-memory (optional FAISS) embedding index over MedDRA PT surfaces."""

    def __init__(self) -> None:
        self.names: List[str] = []
        self.pts: List[str] = []
        self.socs: List[str] = []
        self.codes: List[str] = []
        self.concept_ids: List[Optional[int]] = []
        self.matrix: Optional[np.ndarray] = None
        self._faiss_index = None
        self.backend: str = "empty"
        self._lock = threading.RLock()

    @property
    def size(self) -> int:
        return len(self.names)

    def build(
        self,
        rows: Sequence[dict[str, Any]],
        encoder: SapBERTEncoder,
        *,
        use_cache: bool = True,
    ) -> None:
        with self._lock:
            if not rows:
                self.backend = "empty"
                return

            names = [str(r["name"]) for r in rows]
            cache_key = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:16]

            if use_cache and EMBED_CACHE.exists():
                try:
                    payload = np.load(EMBED_CACHE, allow_pickle=True)
                    if str(payload.get("cache_key", "")) == cache_key:
                        self.names = list(payload["names"])
                        self.pts = list(payload["pts"])
                        self.socs = list(payload["socs"])
                        self.codes = list(payload["codes"])
                        self.concept_ids = [
                            None if x < 0 else int(x) for x in payload["concept_ids"].tolist()
                        ]
                        self.matrix = np.asarray(payload["matrix"], dtype=np.float32)
                        self._maybe_faiss()
                        self.backend = f"cache+{encoder.backend}"
                        LOGGER.info("MedDRA index loaded from cache (%d rows)", self.size)
                        return
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug("MedDRA embed cache miss: %s", exc)

            LOGGER.info("Building MedDRA SapBERT index for %d terms (cold-start possible)…", len(names))
            matrix = encoder.get_embeddings(names)
            self.names = names
            self.pts = [str(r.get("pt") or r["name"]) for r in rows]
            self.socs = [str(r.get("soc") or "") for r in rows]
            self.codes = [str(r.get("code") or "") for r in rows]
            self.concept_ids = [r.get("concept_id") for r in rows]
            self.matrix = np.asarray(matrix, dtype=np.float32)
            self._maybe_faiss()
            self.backend = encoder.backend

            if use_cache:
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    ids = np.asarray(
                        [-1 if c is None else int(c) for c in self.concept_ids],
                        dtype=np.int64,
                    )
                    np.savez_compressed(
                        EMBED_CACHE,
                        cache_key=np.asarray(cache_key),
                        names=np.asarray(self.names, dtype=object),
                        pts=np.asarray(self.pts, dtype=object),
                        socs=np.asarray(self.socs, dtype=object),
                        codes=np.asarray(self.codes, dtype=object),
                        concept_ids=ids,
                        matrix=self.matrix,
                    )
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug("Could not write MedDRA embed cache: %s", exc)

    def _maybe_faiss(self) -> None:
        self._faiss_index = None
        if self.matrix is None or self.matrix.size == 0:
            return
        try:
            import faiss  # type: ignore

            index = faiss.IndexFlatIP(int(self.matrix.shape[1]))
            index.add(self.matrix.astype(np.float32))
            self._faiss_index = index
            self.backend = f"{self.backend}+faiss"
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("FAISS unavailable — numpy cosine: %s", exc)

    def search(self, query_vec: np.ndarray, *, top_k: int = 5) -> List[Tuple[int, float]]:
        if self.matrix is None or self.size == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(1, -1)
        if self._faiss_index is not None:
            scores, idxs = self._faiss_index.search(q, min(top_k, self.size))
            return [
                (int(i), float(s))
                for i, s in zip(idxs[0].tolist(), scores[0].tolist())
                if i >= 0
            ]
        # Numpy cosine (matrix already L2-normalized → dot = cosine)
        sims = (self.matrix @ q.reshape(-1)).astype(np.float32)
        order = np.argsort(-sims)[:top_k]
        return [(int(i), float(sims[i])) for i in order]


class MedDRAResolver:
    """Resolve free-text symptoms / colloquial AEs to MedDRA PT + OMOP concept."""

    def __init__(
        self,
        *,
        session: Optional[AsyncSession] = None,
        engine: Optional[AsyncEngine] = None,
        database_url: Optional[str] = None,
        encoder: Optional[SapBERTEncoder] = None,
        similarity_threshold: float = 0.55,
    ) -> None:
        self._external_session = session
        self._engine = engine
        self._database_url = database_url
        self._encoder = encoder
        self.similarity_threshold = similarity_threshold
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._own_engine = False
        self._index = _MedDRAIndex()
        self._index_ready = False
        self._index_lock = threading.Lock()

    def _get_encoder(self) -> SapBERTEncoder:
        if self._encoder is None:
            self._encoder = get_sapbert_encoder()
        return self._encoder

    async def _ensure_engine(self) -> None:
        if self._external_session is not None or self._engine is not None:
            return
        raw = (self._database_url or os.getenv("DATABASE_URL") or "").strip()
        if not raw:
            try:
                from ..config import settings

                raw = (settings.database_url or "").strip()
            except Exception:
                raw = ""
        if not raw:
            return
        self._engine = create_async_engine(_to_async_url(raw), pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._own_engine = True

    async def aclose(self) -> None:
        if self._own_engine and self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def _session_ctx(self):
        if self._external_session is not None:

            class _Passthrough:
                def __init__(self, s: AsyncSession) -> None:
                    self.s = s

                async def __aenter__(self) -> AsyncSession:
                    return self.s

                async def __aexit__(self, *args: Any) -> None:
                    return None

            return _Passthrough(self._external_session)

        await self._ensure_engine()
        if self._session_factory is None:
            raise RuntimeError("No AsyncSession available")
        return self._session_factory()

    def _lexicon_rows(self) -> List[dict[str, Any]]:
        from .meddra import SOC, _PT_MAP

        rows: List[dict[str, Any]] = []
        seen: set[str] = set()
        for surface, (pt, soc_key) in _PT_MAP.items():
            key = pt.lower()
            if key in seen:
                continue
            seen.add(key)
            soc_label = SOC.get(soc_key, soc_key)
            code = f"MCN:{pt.upper().replace(' ', '_')[:40]}"
            rows.append({
                "name": pt,
                "pt": pt,
                "soc": soc_label,
                "soc_key": soc_key,
                "code": code,
                "concept_id": _stable_id("MedDRA", pt),
                "surface": surface,
            })
            # Also index vernacular-facing surfaces for denser ANN
            if surface.lower() != pt.lower():
                rows.append({
                    "name": surface,
                    "pt": pt,
                    "soc": soc_label,
                    "soc_key": soc_key,
                    "code": code,
                    "concept_id": _stable_id("MedDRA", pt),
                    "surface": surface,
                })
        return rows

    async def _db_meddra_rows(self) -> List[dict[str, Any]]:
        try:
            async with await self._session_ctx() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT concept_id, concept_name, concept_code, concept_class_id
                        FROM omop_concept
                        WHERE vocabulary_id IN ('MedDRA', 'MCN', 'SNOMED', 'SNOMED CT')
                          AND domain_id IN ('Condition', 'Observation', 'Measurement')
                        LIMIT 20000
                        """
                    )
                )
                rows: List[dict[str, Any]] = []
                for row in result.mappings():
                    name = str(row["concept_name"] or "").strip()
                    if not name:
                        continue
                    rows.append({
                        "name": name,
                        "pt": name,
                        "soc": "",
                        "soc_key": "",
                        "code": str(row["concept_code"] or ""),
                        "concept_id": int(row["concept_id"]),
                    })
                return rows
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("MedDRA OMOP pull skipped: %s", exc)
            return []

    async def ensure_index(self, *, force: bool = False) -> dict[str, Any]:
        with self._index_lock:
            if self._index_ready and not force:
                return {"ready": True, "size": self._index.size, "backend": self._index.backend}

        db_rows = await self._db_meddra_rows()
        lex_rows = self._lexicon_rows()
        # Prefer DB concept_ids when names collide
        by_name: Dict[str, dict[str, Any]] = {}
        for r in lex_rows + db_rows:
            key = str(r["name"]).lower()
            prev = by_name.get(key)
            if prev is None or (prev.get("concept_id") and not db_rows):
                by_name[key] = r
            elif r.get("concept_id") is not None:
                by_name[key] = {**prev, **r}

        rows = list(by_name.values())
        encoder = self._get_encoder()
        self._index.build(rows, encoder, use_cache=True)
        self._index_ready = True
        return {
            "ready": True,
            "size": self._index.size,
            "backend": self._index.backend,
            "encoder": encoder.status(),
        }

    async def resolve(self, query: str, *, top_k: int = 5) -> MedDRAResolution:
        q = (query or "").strip()
        if not q:
            return MedDRAResolution(query=q, notes=["Empty query."])

        notes: List[str] = []
        vernacular_canonical: Optional[str] = None

        # 1) Vernacular → lexicon surface
        try:
            from .vernacular import vernacular_lookup
            from .meddra import map_term

            # Extra colloquialisms required by Phase 3 examples
            colloquial_extra = {
                "upset stomach": "nausea",
                "stomach upset": "nausea",
                "tummy upset": "nausea",
                "queasy stomach": "nausea",
                "brain fog": "brain fog",
                "shaky hands": "tremor",
            }
            low = q.lower().strip()
            vern = colloquial_extra.get(low) or vernacular_lookup(q)
            if vern:
                vernacular_canonical = vern
                mapped = map_term(vern)
                if mapped.get("matched"):
                    pt = str(mapped.get("pt") or vern)
                    soc = str(mapped.get("soc") or "")
                    code = f"MCN:{pt.upper().replace(' ', '_')[:40]}"
                    concept_id = await self._lookup_concept_id(pt, code)
                    return MedDRAResolution(
                        query=q,
                        matched=True,
                        match_method="vernacular",
                        concept_id=concept_id,
                        concept_name=pt,
                        meddra_code=code,
                        preferred_term=pt,
                        soc=soc,
                        similarity=0.99,
                        confidence=0.99,
                        vernacular_canonical=vernacular_canonical,
                        notes=notes,
                    )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Vernacular path skipped: {exc}")

        # 2) Exact MedDRA lexicon
        try:
            from .meddra import map_term

            mapped = map_term(q)
            if mapped.get("matched"):
                pt = str(mapped.get("pt") or q)
                soc = str(mapped.get("soc") or "")
                code = f"MCN:{pt.upper().replace(' ', '_')[:40]}"
                concept_id = await self._lookup_concept_id(pt, code)
                return MedDRAResolution(
                    query=q,
                    matched=True,
                    match_method="lexicon_exact",
                    concept_id=concept_id,
                    concept_name=pt,
                    meddra_code=code,
                    preferred_term=pt,
                    soc=soc,
                    similarity=1.0,
                    confidence=1.0,
                    vernacular_canonical=vernacular_canonical,
                    notes=notes,
                )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Lexicon path skipped: {exc}")

        # 3) SapBERT / FAISS semantic retrieval
        await self.ensure_index()
        encoder = self._get_encoder()
        q_vec = encoder.get_embedding(vernacular_canonical or q)
        hits = self._index.search(q_vec, top_k=top_k)
        candidates: List[dict] = []
        for idx, score in hits:
            candidates.append({
                "concept_name": self._index.pts[idx],
                "surface": self._index.names[idx],
                "meddra_code": self._index.codes[idx],
                "soc": self._index.socs[idx],
                "concept_id": self._index.concept_ids[idx],
                "similarity": round(float(score), 4),
            })

        if not candidates or candidates[0]["similarity"] < self.similarity_threshold:
            # Soft fuzzy over lexicon names
            fuzzy = self._fuzzy_lexicon(q)
            if fuzzy is not None:
                return fuzzy.model_copy(
                    update={
                        "vernacular_canonical": vernacular_canonical,
                        "notes": notes + fuzzy.notes,
                    }
                )
            return MedDRAResolution(
                query=q,
                matched=False,
                match_method="semantic_unmatched",
                similarity=float(candidates[0]["similarity"]) if candidates else 0.0,
                confidence=0.0,
                candidates=candidates,
                vernacular_canonical=vernacular_canonical,
                notes=notes
                or ["No MedDRA PT above similarity floor. Try 'nausea', 'brain fog', 'shaky hands'."],
            )

        top = candidates[0]
        return MedDRAResolution(
            query=q,
            matched=True,
            match_method=f"sapbert_{self._index.backend}",
            concept_id=top.get("concept_id"),
            concept_name=top.get("concept_name"),
            meddra_code=top.get("meddra_code"),
            preferred_term=top.get("concept_name"),
            soc=top.get("soc") or None,
            similarity=float(top["similarity"]),
            confidence=float(top["similarity"]),
            candidates=candidates,
            vernacular_canonical=vernacular_canonical,
            notes=notes,
        )

    def _fuzzy_lexicon(self, query: str) -> Optional[MedDRAResolution]:
        try:
            from rapidfuzz import process, fuzz
            from .meddra import _PT_MAP, map_term
        except Exception:
            return None

        choices = list(_PT_MAP.keys())
        hit = process.extractOne(query.lower(), choices, scorer=fuzz.token_sort_ratio)
        if not hit or hit[1] < 80:
            return None
        surface, score, _ = hit
        mapped = map_term(surface)
        pt = str(mapped.get("pt") or surface)
        soc = str(mapped.get("soc") or "")
        code = f"MCN:{pt.upper().replace(' ', '_')[:40]}"
        return MedDRAResolution(
            query=query,
            matched=True,
            match_method="fuzzy_lexicon",
            concept_id=_stable_id("MedDRA", pt),
            concept_name=pt,
            meddra_code=code,
            preferred_term=pt,
            soc=soc,
            similarity=score / 100.0,
            confidence=score / 100.0,
            notes=[],
        )

    async def _lookup_concept_id(self, pt: str, fallback_code: str) -> int:
        try:
            async with await self._session_ctx() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT concept_id FROM omop_concept
                        WHERE vocabulary_id IN ('MedDRA', 'MCN')
                          AND LOWER(concept_name) = LOWER(:pt)
                        LIMIT 1
                        """
                    ),
                    {"pt": pt},
                )
                found = result.scalar_one_or_none()
                if found is not None:
                    return int(found)
        except Exception:
            pass
        return _stable_id("MedDRA", pt or fallback_code)
