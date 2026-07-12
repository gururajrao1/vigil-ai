"""Pre-database 4-gate NLP noise filter (the \"bouncer\").

Runs entirely in-memory on the ingest stream. Tokens that fail any gate are
dropped before ``entities_json`` is written — junk like call/calls/called never
touches the relational store.

Cross-platform *post* duplicates are gated earlier in ``pipeline.ingest_posts``
via ``content_dedupe.ContentDedupeGate`` (semantic narrative SHA-256) so PRR/ROR
are not inflated by syndicated copies.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .negation import detect_negation
from .term_glossary import is_nonclinical_surface
from .text_normalize import run_four_stage_event

logger = logging.getLogger("vigilai.ingest_gateway")

# Conversational / reporting verbs that biomedical NER over-tags as symptoms
_CONVERSATIONAL_VERBS = frozenset({
    "call", "calls", "called", "calling", "say", "says", "said", "saying",
    "post", "posts", "posted", "posting", "tell", "tells", "told", "telling",
    "ask", "asks", "asked", "asking", "write", "writes", "wrote", "writing",
    "read", "reads", "reading", "share", "shares", "shared", "sharing",
    "think", "thinks", "thought", "thinking", "know", "knows", "knew",
    "want", "wants", "wanted", "need", "needs", "needed", "try", "tries",
    "tried", "trying", "take", "takes", "took", "taken", "taking",
    "get", "gets", "got", "getting", "make", "makes", "made", "making",
    "go", "goes", "went", "going", "come", "comes", "came", "coming",
    "thank", "thanks", "thanked", "please", "help", "helped", "helps",
})


def _gate1_medical_entity(surface: str) -> Optional[dict]:
    """Gate 1 — must resolve to a MedDRA-surrogate PT (UMLS/CUI-style acceptance).

    Optional scispaCy enrichment when installed; otherwise lexicon + MedDRA map.
    """
    if not surface or is_nonclinical_surface(surface):
        return None

    # Optional biomedical tokenizer (offline-first: skip if absent)
    try:  # pragma: no cover - optional heavy dep
        import spacy  # type: ignore

        if not hasattr(_gate1_medical_entity, "_nlp"):
            try:
                _gate1_medical_entity._nlp = spacy.load("en_core_sci_sm")  # type: ignore[attr-defined]
            except Exception:
                _gate1_medical_entity._nlp = False  # type: ignore[attr-defined]
        nlp = _gate1_medical_entity._nlp  # type: ignore[attr-defined]
        if nlp:
            doc = nlp(surface)
            # If scispaCy finds no entity-like token and surface is a bare verb-ish
            # token, reject early; multi-word clinical phrases still proceed to map.
            if len(surface.split()) == 1 and not any(ent.label_ for ent in doc.ents):
                tok = doc[0] if len(doc) else None
                if tok is not None and tok.pos_ in {"VERB", "AUX", "ADP", "DET", "PRON"}:
                    return None
    except Exception:
        pass

    resolved = run_four_stage_event(surface)
    if not resolved or not resolved.get("matched", True):
        # run_four_stage_event only returns matched PTs; treat missing as fail
        if not resolved:
            return None
    if not resolved.get("pt"):
        return None
    return resolved


def _gate2_conversational_verb(surface: str) -> bool:
    """Gate 2 — True if surface is a conversational verb / stop-word (DROP)."""
    low = (surface or "").strip().lower()
    if low in _CONVERSATIONAL_VERBS or is_nonclinical_surface(low):
        return True
    # Clinical phenotypes that happen to be verb-like (vomiting, bleeding) must pass
    if run_four_stage_event(surface):
        return False
    # Optional POS tagger — only for still-unmapped single tokens
    try:  # pragma: no cover
        import spacy  # type: ignore

        if not hasattr(_gate2_conversational_verb, "_nlp"):
            try:
                _gate2_conversational_verb._nlp = spacy.load("en_core_web_sm")  # type: ignore[attr-defined]
            except Exception:
                try:
                    _gate2_conversational_verb._nlp = spacy.load("en_core_sci_sm")  # type: ignore[attr-defined]
                except Exception:
                    _gate2_conversational_verb._nlp = False  # type: ignore[attr-defined]
        nlp = _gate2_conversational_verb._nlp  # type: ignore[attr-defined]
        if nlp and len(low.split()) == 1:
            doc = nlp(low)
            if doc and doc[0].pos_ in {"VERB", "AUX"}:
                return True
    except Exception:
        pass
    return False


def _gate3_non_negated(text: str, surface: str, start: int | None, end: int | None,
                       negation_map: dict) -> bool:
    """Gate 3 — True if the symptom mention is NOT negated (KEEP when True)."""
    key = (surface or "").strip().lower()
    # Prefer span-aware map from detect_negation (keyed by normalized)
    if key in negation_map and negation_map[key]:
        return False
    # Heuristic window around the span
    if text and start is not None and end is not None:
        window = text[max(0, start - 40): end + 10].lower()
        for neg in (" no ", " not ", " without ", " never ", "n't ", "nt "):
            if neg in f" {window} ":
                # only reject if negation appears before the surface
                idx = window.find(key[: min(8, len(key))])
                neg_idx = window.find(neg.strip())
                if idx >= 0 and 0 <= neg_idx < idx:
                    return False
    return True


def _gate4_layman_meddra(surface: str, *, full_text: str = "",
                         start: int | None = None, end: int | None = None) -> Optional[dict]:
    """Gate 4 — layman → MedDRA via 3-pass hybrid resolver (context-aware)."""
    from .hybrid_resolver import resolve_event

    return resolve_event(surface, context=full_text, start=start, end=end)


def filter_symptom_entity(
    ent: dict,
    *,
    full_text: str,
    negation_map: dict,
) -> tuple[Optional[dict], str]:
    """Run one symptom span through all four gates.

    Returns (cleaned_entity_or_None, drop_reason).
    """
    surface = (ent.get("text") or ent.get("phrase") or ent.get("normalized") or "").strip()
    if not surface:
        return None, "empty"

    if _gate2_conversational_verb(surface):
        return None, "gate2_conversational_verb"

    if not _gate3_non_negated(
        full_text, surface, ent.get("start"), ent.get("end"), negation_map
    ):
        return None, "gate3_negated"

    # Gate 1 + 4 fused: medical validation then vector/fuzzy MedDRA map
    resolved = _gate1_medical_entity(surface)
    if not resolved:
        resolved = _gate4_layman_meddra(
            surface,
            full_text=full_text,
            start=ent.get("start"),
            end=ent.get("end"),
        )
    if not resolved or not resolved.get("pt"):
        return None, "gate1_or_4_unmapped"

    from .stage3_ner_cui import assign_cui

    out = dict(ent)
    out["pt"] = resolved["pt"]
    out["normalized"] = resolved["pt"].lower()
    out["soc"] = resolved.get("soc")
    out["soc_code"] = resolved.get("soc_code")
    out["norm_stage"] = resolved.get("stage") or resolved.get("method")
    out["similarity"] = resolved.get("similarity")
    out["cui"] = assign_cui(
        kind="event", surface=surface, normalized=out["normalized"], pt=out["pt"]
    )
    out["gateway"] = "passed"
    return out, "ok"


def apply_ingest_gateway(
    text: str,
    entities: Dict[str, List[dict]],
) -> Dict[str, Any]:
    """Synchronous in-memory gateway over ALL entity buckets (pre-DB)."""
    from .condition_norm import canonical_condition
    from .drug_norm import canonical_product
    from .stage3_ner_cui import assign_cui
    from .text_normalize import fold_key

    symptoms = entities.get("symptoms") or []
    negation_map = detect_negation(text, symptoms)

    kept: List[dict] = []
    dropped: List[dict] = []
    seen_pt: set[str] = set()

    for ent in symptoms:
        cleaned, reason = filter_symptom_entity(
            ent, full_text=text, negation_map=negation_map
        )
        if cleaned is None:
            dropped.append({
                "text": ent.get("text") or ent.get("normalized"),
                "reason": reason,
                "bucket": "symptom",
            })
            continue
        pt_key = (cleaned.get("pt") or "").lower()
        if pt_key in seen_pt:
            dropped.append({"text": cleaned.get("text"), "reason": "duplicate_pt", "bucket": "symptom"})
            continue
        seen_pt.add(pt_key)
        kept.append(cleaned)

    # Products — canonical INN only, dedupe by fold
    drugs = []
    seen_drug: set[str] = set()
    for d in entities.get("drugs") or []:
        canon = canonical_product(d.get("normalized") or d.get("text") or "")
        if not canon:
            dropped.append({"text": d.get("text"), "reason": "non_product", "bucket": "drug"})
            continue
        fk = fold_key(canon)
        if fk in seen_drug:
            dropped.append({"text": d.get("text"), "reason": "duplicate_product", "bucket": "drug"})
            continue
        seen_drug.add(fk)
        row = dict(d)
        row["normalized"] = canon
        row["generic"] = canon
        row["cui"] = assign_cui(
            kind="drug", surface=row.get("text") or "", normalized=canon, rxcui=row.get("rxcui")
        )
        row["gateway"] = "passed"
        drugs.append(row)

    # Conditions / indications — lexicon + synonym only (not AE PTs)
    conditions = []
    seen_cond: set[str] = set()
    for c in entities.get("conditions") or []:
        surface = (c.get("normalized") or c.get("text") or "").strip()
        if _gate2_conversational_verb(surface):
            dropped.append({"text": surface, "reason": "gate2_conversational_verb", "bucket": "condition"})
            continue
        canon = canonical_condition(surface)
        if not canon:
            dropped.append({"text": surface, "reason": "unknown_or_junk_condition", "bucket": "condition"})
            continue
        fk = fold_key(canon)
        if fk in seen_cond:
            dropped.append({"text": surface, "reason": "duplicate_condition", "bucket": "condition"})
            continue
        seen_cond.add(fk)
        row = dict(c)
        row["normalized"] = canon
        row["text"] = c.get("text") or surface
        row["cui"] = assign_cui(kind="event", surface=surface, normalized=canon)
        row["gateway"] = "passed"
        conditions.append(row)

    out = {
        "drugs": drugs,
        "symptoms": kept,
        "conditions": conditions,
    }
    trace = {
        "symptoms_in": len(symptoms),
        "symptoms_kept": len(kept),
        "drugs_kept": len(drugs),
        "conditions_kept": len(conditions),
        "dropped_total": len(dropped),
        "dropped": dropped[:50],
    }
    logger.debug(
        "ingest_gateway symptoms=%s drugs=%s conditions=%s dropped=%s",
        len(kept), len(drugs), len(conditions), len(dropped),
    )
    return {"entities": out, "negation": negation_map, "gateway_trace": trace}


async def apply_ingest_gateway_async(
    text: str,
    entities: Dict[str, List[dict]],
) -> Dict[str, Any]:
    """Async wrapper for streaming ingest workers."""
    return await asyncio.to_thread(apply_ingest_gateway, text, entities)
