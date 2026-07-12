"""Transformer biomedical NER (worldwide coverage) with a hard offline fallback.

Uses a HuggingFace token-classification model (default: d4data/biomedical-ner-all)
to recognize drugs / signs-symptoms / diseases in ANY region's text, not just the
curated lexicon. The model is loaded lazily and cached; if transformers/torch are
not installed or the model can't be downloaded, callers silently fall back to the
lexicon matcher. This keeps the app fully runnable offline with zero keys.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, List

from ..config import settings

logger = logging.getLogger("vigilai.ner")

_PIPELINE = None
_LOAD_TRIED = False
_LOCK = threading.Lock()

# d4data/biomedical-ner-all entity groups -> our buckets.
_DRUG_GROUPS = {
    "medication", "drug", "chemical", "pharmacologic_substance",
}
_SYMPTOM_GROUPS = {
    "sign_symptom", "symptom", "clinical_event", "disease_disorder_finding",
}
_CONDITION_GROUPS = {
    "disease_disorder", "disease", "diagnostic_procedure", "biological_structure",
}

# Generic / non-clinical words the model sometimes tags as drug/symptom entities.
# Dropping them prevents junk signals (e.g. "drug -> better").
_NER_STOPWORDS = {
    # generic drug/therapy words
    "drug", "drugs", "medication", "medications", "medicine", "medicines", "med",
    "meds", "pill", "pills", "tablet", "tablets", "capsule", "capsules", "dose",
    "doses", "dosage", "prescription", "prescriptions", "rx", "otc", "mg", "ml",
    "treatment", "therapy", "generic", "brand",
    # sentiment / vague outcome words
    "better", "cured", "cure", "worse", "good", "bad", "fine", "ok", "okay",
    "great", "terrible", "awful", "nice", "help", "helped", "helps", "relief",
    # subword fragments the aggregator emits
    "comb", "ser", "acc", "nurof", "sympt", "ptom", "ause", "tion", "ings",
    "air", "aller", "dia", "par", "pal", "mig", "inc", "ins", "int", "flew",
    "harm", "heat", "drop", "dust", "limp", "lost", "ache", "head", "loss",
    "mood", "not",
    # generic clinical/meta nouns (not actual AEs)
    "symptom", "symptoms", "effect", "effects", "side", "reaction", "reactions",
    "adverse", "adr", "adrs",
    "call", "calls", "called", "calling", "thank", "thanks",
    "take", "takes", "taken", "taking", "took", "broke", "myth", "myths",
    "normal", "desire", "energy", "awake", "appointment", "changes",
    "feelings", "healthy", "invalid", "extension", "discharge", "destroyed",
    "issue", "issues", "problem", "problems", "condition", "conditions",
    "disease", "illness", "health", "body", "system", "level", "levels",
    "thing", "things", "stuff", "lot", "bit", "kind", "type", "sort",
    # time words
    "day", "days", "week", "weeks", "month", "months", "year", "years",
    "today", "tonight", "morning", "night", "time", "times", "hour", "hours",
    # people / places
    "doctor", "doctors", "gp", "hospital", "clinic", "patient", "patients",
    "people", "someone", "everyone", "anyone", "family", "friend", "nurse",
    "mr", "mrs", "dr",
    # common verbs the model over-tags
    "taking", "took", "take", "started", "stopped", "stop", "start", "using",
    "use", "used", "tried", "try", "trying", "feel", "felt", "feeling", "get",
    "got", "going", "need", "want", "made", "make",
}
# Minimum model confidence to accept a transformer entity (raised for precision).
_MIN_SCORE = 0.60


def available() -> bool:
    """Whether transformer NER is enabled and importable (does not force a load)."""
    if not settings.use_transformer_ner:
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _get_pipeline():
    global _PIPELINE, _LOAD_TRIED
    if _PIPELINE is not None or _LOAD_TRIED:
        return _PIPELINE
    with _LOCK:
        if _PIPELINE is not None or _LOAD_TRIED:
            return _PIPELINE
        _LOAD_TRIED = True
        try:
            from transformers import (
                AutoModelForTokenClassification,
                AutoTokenizer,
                pipeline,
            )

            model_name = settings.transformer_ner_model
            logger.info("Loading transformer NER model: %s", model_name)
            tok = AutoTokenizer.from_pretrained(model_name)
            mdl = AutoModelForTokenClassification.from_pretrained(model_name)
            _PIPELINE = pipeline(
                "token-classification",
                model=mdl,
                tokenizer=tok,
                aggregation_strategy="simple",
            )
            logger.info("Transformer NER model ready.")
        except Exception as exc:  # pragma: no cover - depends on env/network
            logger.warning("Transformer NER unavailable, falling back to lexicon: %s", exc)
            _PIPELINE = None
    return _PIPELINE


def _bucket(group: str) -> str | None:
    g = (group or "").strip().lower()
    if g in _DRUG_GROUPS:
        return "drugs"
    if g in _SYMPTOM_GROUPS:
        return "symptoms"
    if g in _CONDITION_GROUPS:
        return "conditions"
    return None


def extract_entities_transformer(text: str) -> Dict[str, List[dict]] | None:
    """Return entity buckets from the transformer, or None if unavailable.

    Each entity: {text, normalized, start, end, source, score}.
    """
    if not text or not available():
        return None
    pipe = _get_pipeline()
    if pipe is None:
        return None
    try:
        raw = pipe(text[:2000])
    except Exception as exc:  # pragma: no cover
        logger.warning("Transformer NER inference failed: %s", exc)
        return None

    out: Dict[str, List[dict]] = {"drugs": [], "symptoms": [], "conditions": []}
    for ent in raw:
        bucket = _bucket(ent.get("entity_group", ""))
        if not bucket:
            continue
        surface = (ent.get("word") or "").strip()
        # Drop WordPiece continuation fragments (e.g. "##uta", "##ne accutane").
        # These are partial subwords the aggregator failed to merge and only add
        # junk drug/symptom entities (and downstream junk signals).
        if "##" in surface:
            continue
        if len(surface) < 3:
            continue
        score = float(ent.get("score", 0.0))
        # Confidence gate + curated stop-list to suppress generic-word false positives.
        if score < _MIN_SCORE:
            continue
        if surface.lower() in _NER_STOPWORDS:
            continue
        # Run AE surfaces through canonical_event so fragments never enter entities_json
        if bucket == "symptoms":
            from .text_normalize import canonical_event
            pt = canonical_event(surface)
            if not pt:
                continue
            out[bucket].append({
                "text": surface,
                "normalized": pt.lower(),
                "pt": pt,
                "start": int(ent.get("start", 0)),
                "end": int(ent.get("end", 0)),
                "source": "transformer",
                "score": round(float(ent.get("score", 0.0)), 3),
            })
            continue
        out[bucket].append({
            "text": surface,
            "normalized": surface.lower(),
            "start": int(ent.get("start", 0)),
            "end": int(ent.get("end", 0)),
            "source": "transformer",
            "score": round(float(ent.get("score", 0.0)), 3),
        })
    return out
