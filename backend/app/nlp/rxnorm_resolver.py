"""RxNorm / brand resolver against ``omop_concept`` (async SQLAlchemy).

Exact + fuzzy (trigram / Levenshtein) match for brands and ingredients in
RxNorm / RxNorm Extension, then hierarchical expansion to active ingredients,
peer brands, ATC class, and RxCUIs via OMOP concept relationships when present,
else the offline RxE surrogate + VigilAI ontology.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

LOGGER = logging.getLogger("vigilai.nlp.rxnorm_resolver")

RXNORM_VOCABS = ("RxNorm", "RxNorm Extension")
BRANDED_CLASSES = {
    "Branded Drug",
    "Branded Drug Comp",
    "Branded Drug Form",
    "Branded Pack",
    "Brand Name",
    "BN",
    "SBD",
    "BPCK",
}
INGREDIENT_CLASSES = {
    "Ingredient",
    "Precise Ingredient",
    "Clinical Drug Comp",
    "IN",
    "PIN",
    "SCDC",
}
_WS_RE = re.compile(r"\s+")


class RxNormResolution(BaseModel):
    """Structured Omni-Search drug payload."""

    query: str
    matched: bool = False
    match_method: str = "unmatched"
    concept_id: Optional[int] = None
    rxcui: Optional[str] = None
    display_name: Optional[str] = None
    brand_names: List[str] = Field(default_factory=list)
    active_ingredients: List[str] = Field(default_factory=list)
    ingredient_rxcuis: List[str] = Field(default_factory=list)
    atc_code: Optional[str] = None
    atc_codes: List[str] = Field(default_factory=list)
    concept_class_id: Optional[str] = None
    vocabulary_id: Optional[str] = None
    confidence: float = 0.0
    notes: List[str] = Field(default_factory=list)


def _normalize(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip().lower())


def _to_async_url(raw: str) -> str:
    url = make_url(raw.strip())
    driver = (url.drivername or "").lower()
    if "asyncpg" in driver:
        return url.render_as_string(hide_password=False)
    if driver in {"postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"}:
        return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    if driver.startswith("sqlite"):
        # aiosqlite path for local offline tests
        if "aiosqlite" not in driver:
            return url.set(drivername="sqlite+aiosqlite").render_as_string(hide_password=False)
        return url.render_as_string(hide_password=False)
    raise ValueError(f"Unsupported DATABASE_URL dialect: {driver!r}")


def _levenshtein_ratio(a: str, b: str) -> float:
    try:
        from rapidfuzz.distance import Levenshtein

        return float(Levenshtein.normalized_similarity(a, b))
    except Exception:
        # Pure-Python fallback
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        la, lb = len(a), len(b)
        prev = list(range(lb + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                ins, delete, sub = cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)
                cur.append(min(ins, delete, sub))
            prev = cur
        dist = prev[-1]
        return 1.0 - (dist / max(la, lb))


def _trigram_set(s: str) -> set[str]:
    padded = f"  {s} "
    return {padded[i : i + 3] for i in range(max(0, len(padded) - 2))}


def _trigram_similarity(a: str, b: str) -> float:
    ta, tb = _trigram_set(a), _trigram_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def _combined_fuzzy(query: str, candidate: str) -> float:
    q, c = _normalize(query), _normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    try:
        from rapidfuzz import fuzz

        token = fuzz.token_sort_ratio(q, c) / 100.0
        partial = fuzz.partial_ratio(q, c) / 100.0
    except Exception:
        token = _levenshtein_ratio(q, c)
        partial = token
    tri = _trigram_similarity(q, c)
    lev = _levenshtein_ratio(q, c)
    return max(token, partial, 0.55 * tri + 0.45 * lev)


class RxNormResolver:
    """Resolve free-text drug / brand queries to OMOP RxNorm concepts."""

    def __init__(
        self,
        *,
        session: Optional[AsyncSession] = None,
        engine: Optional[AsyncEngine] = None,
        database_url: Optional[str] = None,
        fuzzy_threshold: float = 0.72,
    ) -> None:
        self._external_session = session
        self._engine = engine
        self._database_url = database_url
        self.fuzzy_threshold = fuzzy_threshold
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._own_engine = False

    async def _ensure_engine(self) -> Optional[AsyncEngine]:
        if self._external_session is not None:
            return None
        if self._engine is not None:
            return self._engine
        raw = (self._database_url or os.getenv("DATABASE_URL") or "").strip()
        if not raw:
            try:
                from ..config import settings

                raw = (settings.database_url or "").strip()
            except Exception:
                raw = ""
        if not raw:
            return None
        self._engine = create_async_engine(_to_async_url(raw), pool_pre_ping=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._own_engine = True
        return self._engine

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
            raise RuntimeError("No AsyncSession or DATABASE_URL available for RxNormResolver")
        return self._session_factory()

    async def resolve(self, query: str) -> RxNormResolution:
        q = (query or "").strip()
        if not q:
            return RxNormResolution(query=q, notes=["Empty query."])

        notes: List[str] = []
        hit: Optional[dict[str, Any]] = None
        method = "unmatched"
        confidence = 0.0

        try:
            async with await self._session_ctx() as session:
                hit = await self._exact_match(session, q)
                if hit:
                    method = "exact"
                    confidence = 1.0
                else:
                    hit = await self._pg_trgm_match(session, q)
                    if hit:
                        method = "pg_trgm"
                        confidence = float(hit.get("_score") or 0.85)
                    else:
                        hit = await self._fuzzy_scan(session, q)
                        if hit:
                            method = "fuzzy_levenshtein"
                            confidence = float(hit.get("_score") or 0.0)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"OMOP concept lookup unavailable: {exc}")
            LOGGER.warning("RxNorm OMOP lookup failed: %s", exc)

        # Offline RxE / lexicon fallback when DB thin or unmatched
        if hit is None or confidence < self.fuzzy_threshold:
            offline = self._offline_rxe_hit(q)
            if offline is not None:
                return await self._expand_resolution(
                    query=q,
                    concept_row=offline,
                    match_method="rxe_offline" if hit is None else f"{method}+rxe",
                    confidence=max(confidence, float(offline.get("_score") or 0.9)),
                    notes=notes,
                )

        if hit is None or confidence < self.fuzzy_threshold:
            return RxNormResolution(
                query=q,
                matched=False,
                match_method=method,
                confidence=confidence,
                notes=notes
                or ["No RxNorm / RxE match. Try Janumet, Ozempic, Coumadin, or a generic INN."],
            )

        return await self._expand_resolution(
            query=q,
            concept_row=hit,
            match_method=method,
            confidence=confidence,
            notes=notes,
        )

    async def _exact_match(self, session: AsyncSession, query: str) -> Optional[dict[str, Any]]:
        result = await session.execute(
            text(
                """
                SELECT concept_id, concept_name, vocabulary_id, concept_class_id, concept_code
                FROM omop_concept
                WHERE vocabulary_id IN ('RxNorm', 'RxNorm Extension')
                  AND (
                        LOWER(concept_name) = LOWER(:q)
                     OR LOWER(concept_code) = LOWER(:q)
                     OR LOWER(concept_code) = LOWER(:qx)
                  )
                ORDER BY CASE vocabulary_id WHEN 'RxNorm' THEN 0 ELSE 1 END
                LIMIT 1
                """
            ),
            {"q": query, "qx": f"RXCUI:{query}" if query.isdigit() else query},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def _pg_trgm_match(self, session: AsyncSession, query: str) -> Optional[dict[str, Any]]:
        """PostgreSQL pg_trgm similarity when extension is installed."""
        try:
            result = await session.execute(
                text(
                    """
                    SELECT concept_id, concept_name, vocabulary_id, concept_class_id,
                           concept_code, similarity(LOWER(concept_name), LOWER(:q)) AS score
                    FROM omop_concept
                    WHERE vocabulary_id IN ('RxNorm', 'RxNorm Extension')
                      AND concept_name %% :q
                    ORDER BY score DESC
                    LIMIT 1
                    """
                ),
                {"q": query},
            )
            row = result.mappings().first()
            if not row:
                return None
            out = dict(row)
            out["_score"] = float(out.pop("score", 0.0) or 0.0)
            return out if out["_score"] >= self.fuzzy_threshold else None
        except Exception:
            return None

    async def _fuzzy_scan(self, session: AsyncSession, query: str) -> Optional[dict[str, Any]]:
        # Bound scan: prefix / ILIKE candidates then score in Python
        prefix = _normalize(query)[:3]
        result = await session.execute(
            text(
                """
                SELECT concept_id, concept_name, vocabulary_id, concept_class_id, concept_code
                FROM omop_concept
                WHERE vocabulary_id IN ('RxNorm', 'RxNorm Extension')
                  AND (
                        LOWER(concept_name) LIKE :like
                     OR LOWER(concept_name) LIKE :prefix
                  )
                LIMIT 800
                """
            ),
            {"like": f"%{_normalize(query)}%", "prefix": f"{prefix}%"},
        )
        rows = [dict(r) for r in result.mappings().all()]
        if not rows:
            # Wider pull for short misspellings (janumett)
            result = await session.execute(
                text(
                    """
                    SELECT concept_id, concept_name, vocabulary_id, concept_class_id, concept_code
                    FROM omop_concept
                    WHERE vocabulary_id IN ('RxNorm', 'RxNorm Extension')
                    LIMIT 2500
                    """
                )
            )
            rows = [dict(r) for r in result.mappings().all()]

        best: Optional[dict[str, Any]] = None
        best_score = 0.0
        for row in rows:
            score = _combined_fuzzy(query, str(row.get("concept_name") or ""))
            if score > best_score:
                best_score = score
                best = {**row, "_score": score}
        if best is not None and best_score >= self.fuzzy_threshold:
            return best
        return None

    def _offline_rxe_hit(self, query: str) -> Optional[dict[str, Any]]:
        try:
            from ..search_engine import dictionary_cache
            from ..nlp.lexicons import BRAND_TO_GENERIC, atc_for
            from ..nlp.ontology import preferred_generic, resolve_product
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug("Offline RxE import failed: %s", exc)
            return None

        key = _normalize(query)
        brands = dictionary_cache.rxe_brands()
        # Fuzzy over RxE keys
        best_key = None
        best_score = 0.0
        for brand in brands:
            score = _combined_fuzzy(key, brand)
            if score > best_score:
                best_score = score
                best_key = brand
        if best_key and best_score >= self.fuzzy_threshold:
            row = brands[best_key]
            code = str(row.get("brand_rxcui") or f"RXE:{best_key}")
            return {
                "concept_id": abs(hash(code)) % (10**12),
                "concept_name": best_key.title(),
                "vocabulary_id": "RxNorm Extension",
                "concept_class_id": "Branded Drug",
                "concept_code": code,
                "_score": best_score,
                "_rxe": row,
                "_brand_key": best_key,
            }

        # Generic / brand lexicon
        concept = resolve_product(key, online=False)
        generic = preferred_generic(key) or BRAND_TO_GENERIC.get(key)
        if generic or concept.preferred_generic:
            g = concept.preferred_generic or generic or key
            return {
                "concept_id": abs(hash(f"INN:{g}")) % (10**12),
                "concept_name": g.title(),
                "vocabulary_id": "RxNorm",
                "concept_class_id": "Ingredient",
                "concept_code": concept.rxcui or f"INN:{g}",
                "_score": 0.88,
                "_generic": g,
                "_atc": concept.atc or atc_for(g),
            }
        return None

    async def _expand_resolution(
        self,
        *,
        query: str,
        concept_row: dict[str, Any],
        match_method: str,
        confidence: float,
        notes: List[str],
    ) -> RxNormResolution:
        concept_id = int(concept_row["concept_id"]) if concept_row.get("concept_id") is not None else None
        display = str(concept_row.get("concept_name") or query)
        rxcui = str(concept_row.get("concept_code") or "")
        concept_class = str(concept_row.get("concept_class_id") or "")
        vocab = str(concept_row.get("vocabulary_id") or "")

        ingredients: List[str] = []
        ingredient_rxcuis: List[str] = []
        brand_names: List[str] = []
        atc_codes: List[str] = []

        # Prefer RxE payload when present
        rxe = concept_row.get("_rxe")
        if isinstance(rxe, dict):
            brand_names.append(str(concept_row.get("_brand_key") or display).lower())
            for ing in rxe.get("ingredients") or []:
                g = str(ing.get("generic") or "").strip().lower()
                if g and g not in ingredients:
                    ingredients.append(g)
                cui = ing.get("rxcui")
                if cui and str(cui) not in ingredient_rxcuis:
                    ingredient_rxcuis.append(str(cui))
            try:
                from ..nlp.lexicons import atc_for

                for g in ingredients:
                    code = atc_for(g)
                    if code and code not in atc_codes:
                        atc_codes.append(code)
            except Exception:
                pass
            try:
                from ..search_engine.rxnorm_mapper import subset_brands_for_ingredients

                peers = subset_brands_for_ingredients(ingredients)
                for b in peers:
                    if b not in brand_names:
                        brand_names.append(b)
            except Exception:
                pass

        elif concept_row.get("_generic"):
            g = str(concept_row["_generic"]).lower()
            ingredients = [g]
            if rxcui:
                ingredient_rxcuis = [rxcui]
            if concept_row.get("_atc"):
                atc_codes = [str(concept_row["_atc"])]

        else:
            # Live OMOP hierarchy
            try:
                async with await self._session_ctx() as session:
                    rel_ings = await self._relationship_ingredients(session, concept_id)
                    for name, code in rel_ings:
                        if name not in ingredients:
                            ingredients.append(name)
                        if code and code not in ingredient_rxcuis:
                            ingredient_rxcuis.append(code)
                    if concept_class in BRANDED_CLASSES or not ingredients:
                        # If ingredient class already, self is the ingredient
                        if concept_class in INGREDIENT_CLASSES and display.lower() not in ingredients:
                            ingredients.insert(0, display.lower())
                            if rxcui and rxcui not in ingredient_rxcuis:
                                ingredient_rxcuis.insert(0, rxcui)
                    peers = await self._peer_brands(session, ingredients)
                    brand_names.extend(peers)
                    atc_codes.extend(await self._atc_from_db(session, ingredients))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Hierarchy expansion limited: {exc}")
                if concept_class in INGREDIENT_CLASSES:
                    ingredients = [display.lower()]
                    ingredient_rxcuis = [rxcui] if rxcui else []

        if display.lower() not in {b.lower() for b in brand_names} and (
            concept_class in BRANDED_CLASSES or match_method.startswith("rxe")
        ):
            brand_names.insert(0, display)

        # Deduplicate preserving order
        brand_names = list(dict.fromkeys([b for b in brand_names if b]))
        ingredients = list(dict.fromkeys([i for i in ingredients if i]))
        ingredient_rxcuis = list(dict.fromkeys([c for c in ingredient_rxcuis if c]))
        atc_codes = list(dict.fromkeys([a for a in atc_codes if a]))

        if not ingredients and concept_class in INGREDIENT_CLASSES:
            ingredients = [display.lower()]

        return RxNormResolution(
            query=query,
            matched=True,
            match_method=match_method,
            concept_id=concept_id,
            rxcui=rxcui or None,
            display_name=display,
            brand_names=brand_names,
            active_ingredients=ingredients,
            ingredient_rxcuis=ingredient_rxcuis,
            atc_code=atc_codes[0] if atc_codes else None,
            atc_codes=atc_codes,
            concept_class_id=concept_class or None,
            vocabulary_id=vocab or None,
            confidence=round(float(confidence), 4),
            notes=notes,
        )

    async def _relationship_ingredients(
        self, session: AsyncSession, concept_id: Optional[int]
    ) -> List[tuple[str, str]]:
        if concept_id is None:
            return []
        # Try omop_concept_relationship then unprefixed concept_relationship
        for table in ("omop_concept_relationship", "concept_relationship"):
            try:
                result = await session.execute(
                    text(
                        f"""
                        SELECT c.concept_name, c.concept_code, c.concept_class_id
                        FROM {table} AS r
                        JOIN omop_concept AS c
                          ON c.concept_id = r.concept_id_2
                        WHERE r.concept_id_1 = :cid
                          AND LOWER(COALESCE(r.relationship_id, '')) IN (
                                'has_ingredient', 'maps to', 'rxnorm has ing',
                                'has precise ingredient', 'consists of'
                          )
                        """
                    ),
                    {"cid": concept_id},
                )
                out: List[tuple[str, str]] = []
                for row in result.mappings():
                    name = str(row["concept_name"] or "").strip().lower()
                    code = str(row["concept_code"] or "").strip()
                    if name:
                        out.append((name, code))
                if out:
                    return out
            except Exception:
                continue
        return []

    async def _peer_brands(self, session: AsyncSession, ingredients: Sequence[str]) -> List[str]:
        brands: List[str] = []
        for ing in ingredients[:6]:
            result = await session.execute(
                text(
                    """
                    SELECT concept_name FROM omop_concept
                    WHERE vocabulary_id IN ('RxNorm', 'RxNorm Extension')
                      AND concept_class_id IN (
                            'Branded Drug', 'Brand Name', 'BN', 'SBD', 'Branded Drug Comp'
                      )
                      AND LOWER(concept_name) LIKE :pat
                    LIMIT 20
                    """
                ),
                {"pat": f"%{_normalize(ing)}%"},
            )
            for row in result.mappings():
                name = str(row["concept_name"] or "").strip()
                if name and name.lower() not in {b.lower() for b in brands}:
                    brands.append(name)
        return brands

    async def _atc_from_db(self, session: AsyncSession, ingredients: Sequence[str]) -> List[str]:
        codes: List[str] = []
        for ing in ingredients[:6]:
            result = await session.execute(
                text(
                    """
                    SELECT concept_code FROM omop_concept
                    WHERE vocabulary_id = 'ATC'
                      AND (
                            LOWER(concept_name) = LOWER(:ing)
                         OR LOWER(concept_name) LIKE :pat
                      )
                    LIMIT 3
                    """
                ),
                {"ing": ing, "pat": f"{_normalize(ing)}%"},
            )
            for row in result.mappings():
                code = str(row["concept_code"] or "").strip()
                if code and code not in codes:
                    codes.append(code)
        if not codes:
            try:
                from ..nlp.lexicons import atc_for

                for ing in ingredients:
                    c = atc_for(ing)
                    if c and c not in codes:
                        codes.append(c)
            except Exception:
                pass
        return codes
