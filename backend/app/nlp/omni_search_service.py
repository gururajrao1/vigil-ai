"""Unified Omni-Search service — drug vs AE routing to OMOP concept IDs.

Accepts raw Signals search-box text, classifies the entity as a **Drug /
Formulation** or **Adverse Event / Symptom**, then delegates to
``RxNormResolver`` or ``MedDRAResolver``. Returns a single Pydantic v2 payload
suitable for the SPA clinical context and FastAPI JSON responses.

Offline-first: SapBERT cold-start and empty OMOP tables degrade to RxE /
MedDRA-surrogate lexicons without raising.
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .meddra_resolver import MedDRAResolution, MedDRAResolver
from .rxnorm_resolver import RxNormResolution, RxNormResolver
from .sapbert_encoder import get_sapbert_encoder

LOGGER = logging.getLogger("vigilai.nlp.omni_search_service")

_WS_RE = re.compile(r"\s+")


class EntityKind(str, Enum):
    DRUG = "drug"
    ADVERSE_EVENT = "adverse_event"
    UNKNOWN = "unknown"


class OmniSearchHit(BaseModel):
    """Unified Omni-Search JSON for the Signals search box."""

    query: str
    entity_kind: Literal["drug", "adverse_event", "unknown"] = "unknown"
    concept_id: Optional[int] = None
    concept_name: Optional[str] = None
    vocabulary_id: Optional[str] = None
    confidence: float = 0.0
    match_method: str = "unmatched"
    # Drug branch
    rxcui: Optional[str] = None
    brand_names: List[str] = Field(default_factory=list)
    active_ingredients: List[str] = Field(default_factory=list)
    atc_code: Optional[str] = None
    # AE branch
    meddra_code: Optional[str] = None
    preferred_term: Optional[str] = None
    soc: Optional[str] = None
    similarity: Optional[float] = None
    # Diagnostics
    drug_resolution: Optional[RxNormResolution] = None
    ae_resolution: Optional[MedDRAResolution] = None
    classification_scores: dict = Field(default_factory=dict)
    encoder_status: dict = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)
    matched: bool = False


# Strong drug cues (brands / dose forms / Rx tokens)
_DRUG_CUES = re.compile(
    r"\b("
    r"mg|mcg|iu|tablet|capsule|injection|syringe|pen|inhaler|cream|ointment|"
    r"rxcui|ndc|brand|generic|dose|pill"
    r")\b",
    re.I,
)

# Strong AE / symptom cues
_AE_CUES = re.compile(
    r"\b("
    r"pain|ache|nausea|vomit|rash|dizzy|fog|shaky|tremor|bleed|swelling|"
    r"itch|hives|fever|fatigue|insomnia|anxiety|depression|diarrhea|diarrhoea|"
    r"stomach|headache|heart|breath|reaction|side[\s-]?effect|adverse"
    r")\b",
    re.I,
)


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip().lower())


class OmniSearchService:
    """Coordinator for Signals Omni-Search normalization."""

    def __init__(
        self,
        *,
        session: Optional[AsyncSession] = None,
        database_url: Optional[str] = None,
        rxnorm: Optional[RxNormResolver] = None,
        meddra: Optional[MedDRAResolver] = None,
    ) -> None:
        self._session = session
        self._database_url = database_url
        self.rxnorm = rxnorm or RxNormResolver(session=session, database_url=database_url)
        self.meddra = meddra or MedDRAResolver(session=session, database_url=database_url)

    async def aclose(self) -> None:
        await self.rxnorm.aclose()
        await self.meddra.aclose()

    def classify(
        self,
        query: str,
        *,
        drug_hint: Optional[RxNormResolution] = None,
        ae_hint: Optional[MedDRAResolution] = None,
    ) -> tuple[EntityKind, dict[str, float]]:
        """Heuristic + resolver-confidence fusion for drug vs AE."""
        q = _norm(query)
        scores = {"drug": 0.0, "adverse_event": 0.0}

        if _DRUG_CUES.search(q):
            scores["drug"] += 0.35
        if _AE_CUES.search(q):
            scores["adverse_event"] += 0.35

        # Lexicon membership priors
        try:
            from .lexicons import BRAND_TO_GENERIC, GENERIC_DRUGS
            from ..search_engine import dictionary_cache

            if q in GENERIC_DRUGS or q in BRAND_TO_GENERIC:
                scores["drug"] += 0.5
            if q in dictionary_cache.rxe_brands():
                scores["drug"] += 0.55
        except Exception:
            pass

        try:
            from .vernacular import vernacular_lookup
            from .meddra import map_term

            if vernacular_lookup(q) or map_term(q).get("matched"):
                scores["adverse_event"] += 0.55
        except Exception:
            pass

        if drug_hint and drug_hint.matched:
            scores["drug"] += 0.4 * float(drug_hint.confidence or 0.0)
        if ae_hint and ae_hint.matched:
            scores["adverse_event"] += 0.4 * float(ae_hint.confidence or 0.0)

        # Tie-break: multi-word symptom phrases lean AE; single token brand lean drug
        tokens = q.split()
        if len(tokens) >= 2 and scores["adverse_event"] >= scores["drug"] - 0.05:
            scores["adverse_event"] += 0.05
        if len(tokens) == 1 and scores["drug"] >= scores["adverse_event"] - 0.05:
            scores["drug"] += 0.05

        if scores["drug"] <= 0 and scores["adverse_event"] <= 0:
            return EntityKind.UNKNOWN, scores
        if scores["drug"] > scores["adverse_event"] + 0.02:
            return EntityKind.DRUG, scores
        if scores["adverse_event"] > scores["drug"] + 0.02:
            return EntityKind.ADVERSE_EVENT, scores
        # Near-tie: prefer the higher-confidence resolver hit
        if drug_hint and ae_hint:
            if (drug_hint.confidence or 0) >= (ae_hint.confidence or 0):
                return EntityKind.DRUG, scores
            return EntityKind.ADVERSE_EVENT, scores
        if drug_hint and drug_hint.matched:
            return EntityKind.DRUG, scores
        if ae_hint and ae_hint.matched:
            return EntityKind.ADVERSE_EVENT, scores
        return EntityKind.UNKNOWN, scores

    async def search(self, query: str, *, top_k: int = 5) -> OmniSearchHit:
        q = (query or "").strip()
        notes: List[str] = []
        encoder_status: dict[str, Any] = {}
        try:
            encoder_status = get_sapbert_encoder().status()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Encoder status unavailable: {exc}")

        if not q:
            return OmniSearchHit(query=q, notes=["Empty query."], encoder_status=encoder_status)

        # Parallel-ish dual resolve (sequential await — shared session safety)
        drug_res: Optional[RxNormResolution] = None
        ae_res: Optional[MedDRAResolution] = None
        try:
            drug_res = await self.rxnorm.resolve(q)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"RxNormResolver error: {exc}")
            LOGGER.warning("RxNormResolver failed: %s", exc)
            drug_res = RxNormResolution(query=q, notes=[str(exc)])

        try:
            ae_res = await self.meddra.resolve(q, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"MedDRAResolver error: {exc}")
            LOGGER.warning("MedDRAResolver failed: %s", exc)
            ae_res = MedDRAResolution(query=q, notes=[str(exc)])

        kind, scores = self.classify(q, drug_hint=drug_res, ae_hint=ae_res)

        # If classification unknown but one side matched, adopt that side
        if kind == EntityKind.UNKNOWN:
            if drug_res and drug_res.matched and not (ae_res and ae_res.matched):
                kind = EntityKind.DRUG
            elif ae_res and ae_res.matched and not (drug_res and drug_res.matched):
                kind = EntityKind.ADVERSE_EVENT
            elif drug_res and drug_res.matched and ae_res and ae_res.matched:
                kind = (
                    EntityKind.DRUG
                    if (drug_res.confidence or 0) >= (ae_res.confidence or 0)
                    else EntityKind.ADVERSE_EVENT
                )

        if kind == EntityKind.DRUG and drug_res and drug_res.matched:
            notes.extend(drug_res.notes)
            return OmniSearchHit(
                query=q,
                entity_kind="drug",
                concept_id=drug_res.concept_id,
                concept_name=drug_res.display_name,
                vocabulary_id=drug_res.vocabulary_id or "RxNorm",
                confidence=drug_res.confidence,
                match_method=drug_res.match_method,
                rxcui=drug_res.rxcui,
                brand_names=list(drug_res.brand_names),
                active_ingredients=list(drug_res.active_ingredients),
                atc_code=drug_res.atc_code,
                drug_resolution=drug_res,
                ae_resolution=ae_res,
                classification_scores=scores,
                encoder_status=encoder_status,
                notes=notes,
                matched=True,
            )

        if kind == EntityKind.ADVERSE_EVENT and ae_res and ae_res.matched:
            notes.extend(ae_res.notes)
            return OmniSearchHit(
                query=q,
                entity_kind="adverse_event",
                concept_id=ae_res.concept_id,
                concept_name=ae_res.concept_name or ae_res.preferred_term,
                vocabulary_id="MedDRA",
                confidence=ae_res.confidence,
                match_method=ae_res.match_method,
                meddra_code=ae_res.meddra_code,
                preferred_term=ae_res.preferred_term,
                soc=ae_res.soc,
                similarity=ae_res.similarity,
                drug_resolution=drug_res,
                ae_resolution=ae_res,
                classification_scores=scores,
                encoder_status=encoder_status,
                notes=notes,
                matched=True,
            )

        notes.append(
            "Could not map query to an OMOP drug or MedDRA PT. "
            "Try Janumet / sitagliptin or brain fog / nausea / shaky hands."
        )
        if drug_res:
            notes.extend(drug_res.notes)
        if ae_res:
            notes.extend(ae_res.notes)

        return OmniSearchHit(
            query=q,
            entity_kind=kind.value if isinstance(kind, EntityKind) else "unknown",
            confidence=max(scores.get("drug", 0.0), scores.get("adverse_event", 0.0)),
            match_method="unmatched",
            drug_resolution=drug_res,
            ae_resolution=ae_res,
            classification_scores=scores,
            encoder_status=encoder_status,
            notes=notes,
            matched=False,
        )


# Module-level convenience for sync FastAPI routes via asyncio.run / create_task
_SERVICE: Optional[OmniSearchService] = None


def get_omni_search_service(**kwargs: Any) -> OmniSearchService:
    global _SERVICE
    if _SERVICE is None or kwargs:
        _SERVICE = OmniSearchService(**kwargs)
    return _SERVICE


async def omni_normalize(query: str, *, session: Optional[AsyncSession] = None) -> OmniSearchHit:
    """One-shot async helper used by API / MCP adapters."""
    svc = OmniSearchService(session=session) if session is not None else get_omni_search_service()
    return await svc.search(query)
