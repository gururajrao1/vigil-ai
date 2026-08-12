"""MCN pipeline orchestrator — clinical + geographic entity normalization."""
from __future__ import annotations

from typing import List, Optional

from . import catalog
from .clinical_aggregator import aggregate_clinical_cohorts, diabetes_demo_cohort
from .geo_normalizer import get_geo_normalizer, normalize_location
from .models import (
    MCN_VERSION,
    AuditStamp,
    ClinicalGeoNormalization,
    CohortAggregationResult,
    ConceptLink,
    EvalMetrics,
    MappingTracePayload,
)
from .sapbert_encoder import get_encoder
from .umls_linker import get_linker, link_to_umls


def _audit() -> AuditStamp:
    linker = get_linker()
    return AuditStamp(
        encoder_backend=linker.backend,
        faiss_enabled=linker.faiss_enabled,
        dictionaries=catalog.loaded_files(),
    )


def normalize_clinical_term(raw_clinical_term: str, *, top_k: int = 5) -> ConceptLink:
    return link_to_umls(raw_clinical_term, top_k=top_k)


def mapping_trace(raw_clinical_term: str) -> MappingTracePayload:
    clinical = normalize_clinical_term(raw_clinical_term)
    steps = [
        {
            "step": "1",
            "name": "sapbert_encoder",
            "detail": (
                f"Embedded «{raw_clinical_term}» with {clinical.embedding.encoder_backend if clinical.embedding else 'n/a'} "
                f"→ {clinical.embedding.vector_dim if clinical.embedding else '?'}-d vector"
            ),
        },
        {
            "step": "2",
            "name": "umls_linker",
            "detail": (
                f"Cosine / alias search → CUI={clinical.cui or '—'} "
                f"({clinical.match_method}, cosine={clinical.cosine})"
            ),
        },
        {
            "step": "3",
            "name": "mednorm_bergamot",
            "detail": (
                f"Dual map MedDRA PT={clinical.meddra_pt or '—'} · "
                f"SNOMED-CT={clinical.snomed_ct or '—'}"
            ),
        },
    ]
    return MappingTracePayload(clinical=clinical, pipeline_steps=steps, audit=_audit())


def normalize_clinical_and_geo_entities(
    raw_clinical_term: str,
    raw_location: str = "",
) -> ClinicalGeoNormalization:
    """FastMCP / API entry: noisy clinical + geo → structured JSON."""
    clinical = normalize_clinical_term(raw_clinical_term)
    geography = normalize_location(raw_location) if (raw_location or "").strip() else normalize_location("")
    return ClinicalGeoNormalization(
        raw_clinical_term=raw_clinical_term or "",
        raw_location=raw_location or "",
        clinical=clinical,
        geography=geography,
        audit=_audit(),
    )


def engine_status() -> dict:
    enc = get_encoder()
    linker = get_linker()
    geo = get_geo_normalizer()
    return {
        "version": MCN_VERSION,
        "pipeline": [
            "1 sapbert_encoder (SapBERT / ngram dense vectors)",
            "2 umls_linker (FAISS cosine k-NN → UMLS CUI)",
            "3 clinical_aggregator (synonym collapse + cohort N)",
            "4 geo_normalizer (GeoNames-style municipal aliases)",
            "5 eval (Mantra GSC / CADEC-inspired F1 gate)",
        ],
        "encoder_backend": enc.backend,
        "encoder_dim": enc.dim,
        "faiss_enabled": linker.faiss_enabled,
        "linker_backend": linker.backend,
        "geo_alias_count": len(geo._alias_index),
        **catalog.catalog_counts(),
        "disclaimer": _audit().disclaimer,
    }


def evaluate_clinical_f1(cases: Optional[List[dict]] = None) -> EvalMetrics:
    """Precision / recall / F1 against gold CUIs (Mantra/CADEC-inspired sample)."""
    gold = cases if cases is not None else catalog.load_eval_sample().get("clinical_cases", [])
    tp = fp = fn = 0
    for case in gold:
        pred = link_to_umls(case["verbatim"])
        gold_cui = case.get("gold_cui")
        gold_pt = (case.get("gold_pt") or "").lower()
        ok = False
        if pred.matched:
            if gold_cui and pred.cui == gold_cui:
                ok = True
            elif gold_pt and (pred.meddra_pt or "").lower() == gold_pt:
                ok = True
            if ok:
                tp += 1
            else:
                fp += 1
                fn += 1  # missed the gold concept
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return EvalMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        n_cases=len(gold),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        scope="clinical",
    )


def evaluate_geo_f1(cases: Optional[List[dict]] = None) -> EvalMetrics:
    gold = cases if cases is not None else catalog.load_eval_sample().get("geo_cases", [])
    tp = fp = fn = 0
    for case in gold:
        pred = normalize_location(case["verbatim"])
        gold_c = case.get("gold_canonical")
        if pred.matched and pred.canonical == gold_c:
            tp += 1
        elif pred.matched:
            fp += 1
            fn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return EvalMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        n_cases=len(gold),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        scope="geo",
    )


__all__ = [
    "aggregate_clinical_cohorts",
    "diabetes_demo_cohort",
    "engine_status",
    "evaluate_clinical_f1",
    "evaluate_geo_f1",
    "mapping_trace",
    "normalize_clinical_and_geo_entities",
    "normalize_clinical_term",
    "normalize_location",
    "CohortAggregationResult",
]
