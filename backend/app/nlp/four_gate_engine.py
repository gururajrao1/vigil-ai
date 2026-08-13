"""4-Gate Deterministic NLP Engine — Phase 2 predictive intelligence facade.

Wraps VigilAI's offline AE detector with BioIE-inspired naming and richer
explainability traces:

  Gate 1 — Brand→Generic concept normalization (TaggerOne / DNorm–inspired)
  Gate 2 — Ontology mapping (text → UMLS-style CUI → MedDRA PT / GMDN)
  Gate 3 — Sentiment & polarity filtering (VADER offline; RoBERTa when available)
  Gate 4 — Contextual non-negation (ConText / negBio–style rules)

Offline-first: BioBERT / ClinicalBERT / scispaCy load only when installed;
otherwise lexicon + transformer NER fallback already in ``entities.py``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .ae_detector import (
    DEFAULT_NEGATIVE_THRESHOLD,
    detect_ae,
    evaluate_ae_text,
    unique_drug_concepts,
    unique_symptom_concepts,
)
from .drug_norm import normalize as normalize_drug
from .meddra import map_term
from .ontology import resolve_product
from .stage3_ner_cui import assign_cui

logger = logging.getLogger("vigilai.four_gate")

# Polarity discard band: near-neutral promotional / humorous chatter
DEFAULT_POLARITY_DISCARD = 0.10

GATE_NAMES = {
    1: "brand_to_generic_normalization",
    2: "medical_ontology_mapping",
    3: "sentiment_polarity_filter",
    4: "contextual_non_negation",
}


def _gate1_normalize_drugs(drugs: List[dict]) -> List[dict]:
    """TaggerOne/DNorm-style collapse: brand/typo → preferred generic + ATC."""
    out: List[dict] = []
    for d in drugs or []:
        surface = (d.get("text") or d.get("normalized") or "").strip()
        if not surface:
            continue
        info = normalize_drug(surface)
        concept = resolve_product(info.get("generic") or surface)
        preferred = concept.preferred_generic or info.get("generic") or surface.lower()
        row = dict(d)
        row["normalized"] = preferred
        row["generic"] = preferred
        row["atc"] = info.get("atc") or concept.atc
        row["rxcui"] = info.get("rxcui") or concept.rxcui
        row["concept_id"] = concept.concept_id or d.get("concept_id")
        row["ontology_aliases"] = concept.aliases()[:12]
        row["cui"] = d.get("cui") or assign_cui(
            kind="drug",
            surface=surface,
            normalized=preferred,
            rxcui=row.get("rxcui"),
        )
        out.append(row)
    return out


def _gate2_map_events(symptoms: List[dict], devices: bool = False) -> List[dict]:
    """Map lay/slang symptoms → MedDRA-style PT/SOC + UMLS-style CUI."""
    out: List[dict] = []
    for s in symptoms or []:
        surface = (s.get("text") or s.get("normalized") or "").strip()
        if not surface:
            continue
        row = dict(s)
        if not row.get("pt"):
            mapped = map_term(surface)
            row["pt"] = mapped.get("pt") or surface.lower()
            row["soc"] = mapped.get("soc")
            row["soc_code"] = mapped.get("soc_code")
            row["normalized"] = row["pt"]
        row["cui"] = row.get("cui") or assign_cui(
            kind="symptom",
            surface=surface,
            normalized=row.get("normalized") or row.get("pt") or "",
            pt=row.get("pt"),
        )
        out.append(row)
    return out


def _try_roberta_sentiment(text: str) -> Optional[dict]:
    """Optional fine-tuned RoBERTa polarity; None → use VADER path."""
    try:
        from .bionlp_optional import roberta_sentiment

        return roberta_sentiment(text)
    except Exception:
        return None


def run_four_gates(
    text: str,
    *,
    use_transformer: bool | None = False,
    use_optional_bionlp: bool = False,
    negative_threshold: float = DEFAULT_NEGATIVE_THRESHOLD,
    polarity_discard: float = DEFAULT_POLARITY_DISCARD,
    discard_near_neutral: bool = True,
) -> Dict[str, Any]:
    """Execute the full 4-gate pipeline on raw text with explainability traces.

    Optional RoBERTa / scispaCy stay off by default so API/UI stay snappy;
    pass ``use_optional_bionlp=True`` when local weights are already cached.
    """
    from .bionlp_optional import optional_backends_status, scispacy_entities
    from .entities import extract_entities
    from .negation import detect_negation
    from .sentiment import analyze_sentiment

    ents = extract_entities(text or "", use_transformer=use_transformer)
    # Optional scispaCy merge (opt-in) — does not replace lexicon
    if use_optional_bionlp:
        sci = scispacy_entities(text or "")
        if sci:
            ents = {
                "drugs": list(ents.get("drugs") or []) + list(sci.get("drugs") or []),
                "symptoms": list(ents.get("symptoms") or []) + list(sci.get("symptoms") or []),
                "conditions": list(ents.get("conditions") or []) + list(sci.get("conditions") or []),
            }

    drugs = _gate1_normalize_drugs(ents.get("drugs") or [])
    symptoms = _gate2_map_events(ents.get("symptoms") or [])
    ents = {**ents, "drugs": drugs, "symptoms": symptoms}

    sent = None
    if use_optional_bionlp:
        sent = _try_roberta_sentiment(text)
    sent = sent or analyze_sentiment(text or "")
    # Gate 3 polarity discard: near-zero compound → promotional/neutral noise
    polarity_abs = abs(float(sent.get("score") or 0.0))
    discarded_neutral = bool(
        discard_near_neutral
        and polarity_abs < polarity_discard
        and (sent.get("label") or "").upper() == "NEUTRAL"
    )

    neg = detect_negation(text or "", symptoms)
    ae = detect_ae(
        ents,
        sent,
        neg,
        negative_threshold=negative_threshold,
    )

    if discarded_neutral:
        ae = {
            **ae,
            "ae_flag": False,
            "confidence": 0.0,
            "reason": (
                f"Discarded near-neutral polarity (|score|={polarity_abs:.3f} "
                f"< {polarity_discard}) — promotional/humorous filter"
            ),
        }

    drug_concepts = unique_drug_concepts(drugs)
    symptom_concepts = unique_symptom_concepts(symptoms)

    traces = []
    for g in ae.get("gate_trace") or []:
        gate_n = int(g.get("gate") or 0)
        traces.append({
            **g,
            "bioie_name": GATE_NAMES.get(gate_n, g.get("name")),
            "inspiration": {
                1: "TaggerOne/DNorm brand→concept collapse + ATC/RxNorm",
                2: "BioBERT/scispaCy-style linking via MedDRA surrogate + CUI",
                3: "RoBERTa/VADER polarity; discard |polarity| < threshold",
                4: "ConText/negBio negation cues over symptom spans",
            }.get(gate_n),
        })

    return {
        "text_len": len(text or ""),
        "ae_flag": bool(ae.get("ae_flag")),
        "ae_confidence": float(ae.get("confidence") or 0.0),
        "reason": ae.get("reason"),
        "discarded_near_neutral": discarded_neutral,
        "sentiment": sent,
        "entities": {
            "drugs": drugs,
            "symptoms": symptoms,
            "conditions": ents.get("conditions") or [],
        },
        "drug_concepts": drug_concepts,
        "symptom_concepts": symptom_concepts,
        "negation": neg,
        "gate_trace": traces,
        "explainability": ae.get("explainability") or {},
        "optional_backends": optional_backends_status(),
        "use_optional_bionlp": use_optional_bionlp,
        "pipeline": "four_gate_engine_v1",
        "offline": True,
        "disclaimer": (
            "Deterministic 4-gate AE engine with open ontology surrogates. "
            "Open MedDRA/UMLS-style coding."
        ),
    }


def evaluate_stream(
    records: List[Dict[str, Any]],
    *,
    text_key: str = "body",
    use_transformer: bool = False,
) -> List[Dict[str, Any]]:
    """Batch 4-gate evaluation over ingest-style dicts."""
    out = []
    for rec in records:
        text = rec.get(text_key) or rec.get("text") or ""
        title = rec.get("title") or ""
        combined = f"{title}\n{text}".strip()
        result = run_four_gates(combined, use_transformer=use_transformer)
        out.append({**result, "external_id": rec.get("external_id")})
    return out


# Re-export for callers that want the classic path
__all__ = [
    "GATE_NAMES",
    "run_four_gates",
    "evaluate_stream",
    "evaluate_ae_text",
    "detect_ae",
]
