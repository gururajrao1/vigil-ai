"""Optional local BioNLP backends — never block cold start or require network.

RoBERTa sentiment and scispaCy entity linking load only when:
  * the package is installed, AND
  * the model weights are already on disk (``local_files_only=True``).

Otherwise callers fall back to VADER / lexicon NER immediately.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vigilai.bionlp_optional")

_SENT_PIPE = None
_SENT_TRIED = False
_SENT_LOCK = threading.Lock()

_SCISPACY_NLP = None
_SCISPACY_TRIED = False
_SCISPACY_LOCK = threading.Lock()


def roberta_sentiment(text: str) -> Optional[dict]:
    """Fine-tuned RoBERTa polarity when a local model is already cached.

    Returns ``{label, score, model}`` or ``None`` to signal VADER fallback.
    """
    global _SENT_PIPE, _SENT_TRIED
    if not (text or "").strip():
        return None
    if _SENT_TRIED and _SENT_PIPE is None:
        return None
    with _SENT_LOCK:
        if not _SENT_TRIED:
            _SENT_TRIED = True
            try:
                from importlib.util import find_spec

                if not find_spec("transformers"):
                    return None
                from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

                model_id = "cardiffnlp/twitter-roberta-base-sentiment-latest"
                tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
                model = AutoModelForSequenceClassification.from_pretrained(
                    model_id, local_files_only=True
                )
                _SENT_PIPE = pipeline(
                    "sentiment-analysis",
                    model=model,
                    tokenizer=tokenizer,
                    top_k=None,
                )
                logger.info("RoBERTa sentiment loaded from local cache")
            except Exception as exc:
                logger.debug("RoBERTa sentiment unavailable (%s) — VADER fallback", exc)
                _SENT_PIPE = None
                return None
        if _SENT_PIPE is None:
            return None
    try:
        raw = _SENT_PIPE(text[:512])
        # pipeline may return [[{label, score}, ...]] or [{label, score}]
        rows = raw[0] if raw and isinstance(raw[0], list) else raw
        best = max(rows, key=lambda x: float(x.get("score") or 0.0))
        label_raw = str(best.get("label") or "").lower()
        score = float(best.get("score") or 0.0)
        if "neg" in label_raw:
            label, compound = "NEGATIVE", -score
        elif "pos" in label_raw:
            label, compound = "POSITIVE", score
        else:
            label, compound = "NEUTRAL", 0.0
        return {"label": label, "score": compound, "model": "roberta_local"}
    except Exception as exc:
        logger.debug("RoBERTa inference failed: %s", exc)
        return None


def scispacy_entities(text: str) -> Optional[Dict[str, List[dict]]]:
    """Optional scispaCy NER when ``en_core_sci_sm`` (or similar) is installed."""
    global _SCISPACY_NLP, _SCISPACY_TRIED
    if not (text or "").strip():
        return None
    if _SCISPACY_TRIED and _SCISPACY_NLP is None:
        return None
    with _SCISPACY_LOCK:
        if not _SCISPACY_TRIED:
            _SCISPACY_TRIED = True
            try:
                import spacy

                for model in ("en_core_sci_sm", "en_core_sci_md", "en_ner_bc5cdr_md"):
                    try:
                        _SCISPACY_NLP = spacy.load(model)
                        logger.info("scispaCy model loaded: %s", model)
                        break
                    except Exception:
                        continue
            except Exception as exc:
                logger.debug("scispaCy unavailable: %s", exc)
                _SCISPACY_NLP = None
                return None
        if _SCISPACY_NLP is None:
            return None
    try:
        doc = _SCISPACY_NLP(text[:5000])
        drugs, symptoms, conditions = [], [], []
        for ent in doc.ents:
            label = (ent.label_ or "").upper()
            row = {
                "text": ent.text,
                "start": ent.start_char,
                "end": ent.end_char,
                "source": "scispacy",
                "normalized": ent.text.lower(),
            }
            if label in ("CHEMICAL", "DRUG", "SIMPLE_CHEMICAL"):
                drugs.append(row)
            elif label in ("DISEASE", "DISORDER", "FINDING", "SIGN_OR_SYMPTOM"):
                symptoms.append(row)
            else:
                conditions.append(row)
        return {"drugs": drugs, "symptoms": symptoms, "conditions": conditions}
    except Exception as exc:
        logger.debug("scispaCy inference failed: %s", exc)
        return None


def optional_backends_status() -> dict:
    """Cheap status for UI / health — does not force model load."""
    from importlib.util import find_spec

    return {
        "transformers_installed": bool(find_spec("transformers")),
        "spacy_installed": bool(find_spec("spacy")),
        "roberta_loaded": _SENT_PIPE is not None,
        "scispacy_loaded": _SCISPACY_NLP is not None,
        "roberta_tried": _SENT_TRIED,
        "scispacy_tried": _SCISPACY_TRIED,
        "note": (
            "Optional models load only when already cached on disk "
            "(local_files_only). Otherwise VADER + lexicon NER stay active."
        ),
    }
