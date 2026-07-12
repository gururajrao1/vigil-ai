"""Explainable 4-gate adverse-event validation engine (Algo-Pharma lineage).

Pipeline (dynamic — no hardcoded drug variables):

  Gate 1  Unique drug *concept* present
          Brand/generic surfaces collapse via normalize → set of distinct concepts.
          CRITICAL: "Lyrica" + "Pregabalin" count as ONE concept, not two.

  Gate 2  Symptom / medical event present (count of extracted symptoms > 0)

  Gate 3  Negative sentiment (adverse threshold — NEGATIVE label or score ≤ τ)

  Gate 4  At least one NON-negated symptom (contextual cues: no/not/without/denies…)

Payload always exposes UI-ready explainability::

    explainability.gate_1 = {"status": bool, "count": int, "items": list, ...}

``detect_ae`` remains the in-pipeline entry used by ``pipeline._process_raw``.
``evaluate_ae_text`` is the dataset-agnostic stream processor (Kaggle ADE,
openFDA narratives, forums, etc.) with injectable extractors.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

# Sentiment compound ≤ this (or explicit NEGATIVE label) passes Gate 3.
DEFAULT_NEGATIVE_THRESHOLD = -0.05


# --------------------------------------------------------------------------- #
# Concept-level de-duplication (Gate 1)
# --------------------------------------------------------------------------- #

def _concept_key(entity: Mapping[str, Any]) -> str:
    """Stable drug/device concept id: prefer generic / CUI / normalized label."""
    for field in ("generic", "cui", "normalized", "pt", "text"):
        val = entity.get(field)
        if val:
            return str(val).strip().lower()
    return ""


def unique_drug_concepts(
    drugs: Sequence[Mapping[str, Any]],
    *,
    brand_map: Optional[Mapping[str, str]] = None,
) -> List[dict]:
    """Collapse brand + generic (and multi-span) hits into distinct concepts.

    ``brand_map`` is optional (surface → generic). When omitted we trust each
    entity's ``generic`` / ``normalized`` fields (pipeline already runs drug_norm).
    """
    seen: set[str] = set()
    unique: List[dict] = []
    for raw in drugs or []:
        surface = str(raw.get("text") or raw.get("surface") or "").strip()
        concept = _concept_key(raw)
        if brand_map and surface:
            mapped = brand_map.get(surface.lower()) or brand_map.get(concept)
            if mapped:
                concept = str(mapped).strip().lower()
        if not concept:
            continue
        if concept in seen:
            # Attach alternate surface for audit without inflating the count.
            for u in unique:
                if u["concept"] == concept and surface and surface not in u["surfaces"]:
                    u["surfaces"].append(surface)
                    break
            continue
        seen.add(concept)
        unique.append({
            "concept": concept,
            "generic": str(raw.get("generic") or concept).strip().lower(),
            "surfaces": [surface] if surface else [],
            "atc": raw.get("atc"),
            "rxcui": raw.get("rxcui"),
            "source": raw.get("source"),
        })
    return unique


def unique_symptom_concepts(symptoms: Sequence[Mapping[str, Any]]) -> List[dict]:
    """Distinct symptom / PT concepts (preserve first span metadata)."""
    seen: set[str] = set()
    unique: List[dict] = []
    for raw in symptoms or []:
        key = str(raw.get("normalized") or raw.get("pt") or raw.get("text") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append({
            "concept": key,
            "pt": raw.get("pt") or key,
            "soc": raw.get("soc"),
            "text": raw.get("text"),
            "negated": None,  # filled at Gate 4
        })
    return unique


# --------------------------------------------------------------------------- #
# Gate builders
# --------------------------------------------------------------------------- #

def _gate_payload(
    *,
    gate: int,
    name: str,
    status: bool,
    count: int,
    items: List[Any],
    detail: str,
    extra: Optional[dict] = None,
) -> dict:
    row = {
        "gate": gate,
        "name": name,
        "passed": status,          # legacy UI key
        "status": status,          # schema key requested by frontend contract
        "count": count,
        "items": items,
        "detail": detail,
    }
    if extra:
        row.update(extra)
    return row


def detect_ae(
    entities: Dict[str, List[dict]],
    sentiment: dict,
    negation: Dict[str, bool],
    *,
    negative_threshold: float = DEFAULT_NEGATIVE_THRESHOLD,
    brand_map: Optional[Mapping[str, str]] = None,
) -> dict:
    """Run the 4-gate engine on already-extracted entities + sentiment + negation.

    Returns ae_flag, confidence, reason, gate_trace (list), and explainability
    (dict keyed gate_1…gate_4) for UI components.
    """
    drugs_raw = entities.get("drugs") or []
    symptoms_raw = entities.get("symptoms") or []

    # --- Gate 1: unique normalized drug concepts ---
    drug_concepts = unique_drug_concepts(drugs_raw, brand_map=brand_map)
    drug_items = [d["concept"] for d in drug_concepts]
    g1 = len(drug_concepts) > 0
    gate1 = _gate_payload(
        gate=1,
        name="unique_drug_present",
        status=g1,
        count=len(drug_concepts),
        items=drug_items,
        detail=(
            f"{len(drug_concepts)} unique drug concept(s)"
            f" (from {len(drugs_raw)} surface hit(s))"
        ),
        extra={"surfaces": {d["concept"]: d["surfaces"] for d in drug_concepts}},
    )

    # --- Gate 2: symptom present ---
    symptom_concepts = unique_symptom_concepts(symptoms_raw)
    symptom_items = [s["concept"] for s in symptom_concepts]
    g2 = len(symptom_concepts) > 0
    gate2 = _gate_payload(
        gate=2,
        name="symptom_present",
        status=g2,
        count=len(symptom_concepts),
        items=symptom_items,
        detail=f"{len(symptom_concepts)} unique symptom(s)",
    )

    # --- Gate 3: negative / adverse sentiment ---
    label = (sentiment or {}).get("label")
    score = float((sentiment or {}).get("score") or 0.0)
    g3 = label == "NEGATIVE" or score <= negative_threshold
    gate3 = _gate_payload(
        gate=3,
        name="negative_sentiment",
        status=g3,
        count=1 if g3 else 0,
        items=[{"label": label, "score": score}],
        detail=f"{label} ({score})",
        extra={"threshold": negative_threshold},
    )

    # --- Gate 4: non-negated symptom ---
    non_negated: List[str] = []
    negated: List[str] = []
    for s in symptom_concepts:
        key = s["concept"]
        is_neg = bool(negation.get(key, False))
        s["negated"] = is_neg
        if is_neg:
            negated.append(key)
        else:
            non_negated.append(key)
    g4 = len(non_negated) > 0
    gate4 = _gate_payload(
        gate=4,
        name="non_negated_symptom",
        status=g4,
        count=len(non_negated),
        items=non_negated,
        detail=f"{len(non_negated)} non-negated / {len(negated)} negated",
        extra={"negated_items": negated},
    )

    gates = [gate1, gate2, gate3, gate4]
    passed_all = g1 and g2 and g3 and g4

    if passed_all:
        confidence = round(min(0.99, abs(score) * 0.9 + 0.1), 3)
        reason = "drug + symptom + negative_sentiment + non_negated_symptom"
    else:
        confidence = 0.0
        first_fail = next((g for g in gates if not g["status"]), None)
        reason = (
            f"failed_gate_{first_fail['gate']}:{first_fail['name']}"
            if first_fail else "unknown"
        )

    explainability = {
        "gate_1": {k: gate1[k] for k in ("status", "count", "items", "name", "detail", "surfaces") if k in gate1},
        "gate_2": {k: gate2[k] for k in ("status", "count", "items", "name", "detail")},
        "gate_3": {k: gate3[k] for k in ("status", "count", "items", "name", "detail", "threshold") if k in gate3},
        "gate_4": {k: gate4[k] for k in ("status", "count", "items", "name", "detail", "negated_items") if k in gate4},
    }

    return {
        "ae_flag": passed_all,
        "confidence": confidence,
        "reason": reason,
        "gate_trace": gates,                 # list form (Signal Detail GateTrace)
        "explainability": explainability,   # dict form (frontend schema contract)
        "unique_drug_count": len(drug_concepts),
        "unique_symptom_count": len(symptom_concepts),
        "non_negated_symptoms": non_negated,
        "drug_concepts": drug_concepts,
        "symptom_concepts": symptom_concepts,
    }


# --------------------------------------------------------------------------- #
# Dataset-agnostic stream processor
# --------------------------------------------------------------------------- #

ExtractorFn = Callable[[str], Dict[str, List[dict]]]
SentimentFn = Callable[[str], dict]
NegationFn = Callable[[str, List[dict]], Dict[str, bool]]


def evaluate_ae_text(
    text: str,
    *,
    extract_entities: Optional[ExtractorFn] = None,
    analyze_sentiment: Optional[SentimentFn] = None,
    detect_negation: Optional[NegationFn] = None,
    brand_map: Optional[Mapping[str, str]] = None,
    negative_threshold: float = DEFAULT_NEGATIVE_THRESHOLD,
    use_transformer: bool = False,
    meta: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Process one unstructured narrative (any dataset) through the 4-gate engine.

    Inject custom extractors for Kaggle ADE / openFDA / etc., or omit them to
    use VigilAI's offline-first lexicon + VADER + windowed negation stack.
    """
    text = (text or "").strip()
    if extract_entities is None:
        from .entities import extract_entities as _extract
        extract_entities = lambda t: _extract(t, use_transformer=use_transformer)  # noqa: E731
    if analyze_sentiment is None:
        from .sentiment import analyze_sentiment as _sent
        analyze_sentiment = _sent
    if detect_negation is None:
        from .negation import detect_negation as _neg
        detect_negation = _neg
    if brand_map is None:
        try:
            from .lexicons import BRAND_TO_GENERIC
            brand_map = BRAND_TO_GENERIC
        except Exception:
            brand_map = {}

    entities = extract_entities(text) if text else {"drugs": [], "symptoms": [], "conditions": []}
    sentiment = analyze_sentiment(text) if text else {"label": "NEUTRAL", "score": 0.0}
    negation = detect_negation(text, entities.get("symptoms") or []) if text else {}

    result = detect_ae(
        entities,
        sentiment,
        negation,
        negative_threshold=negative_threshold,
        brand_map=brand_map,
    )
    result["text"] = text
    result["entities"] = entities
    result["sentiment"] = sentiment
    result["negation"] = negation
    if meta:
        result["meta"] = dict(meta)
    return result


def evaluate_ae_stream(
    records: Iterable[Mapping[str, Any]],
    *,
    text_field: str = "text",
    id_field: str = "id",
    **kwargs: Any,
) -> List[dict]:
    """Batch-evaluate a stream of dict records (Kaggle ADE rows, FAERS narratives…).

    Each record must expose ``text_field``. Optional ``id_field`` is copied into meta.
    Extra kwargs are forwarded to ``evaluate_ae_text``.
    """
    out: List[dict] = []
    for i, rec in enumerate(records):
        if not isinstance(rec, Mapping):
            continue
        text = rec.get(text_field) or rec.get("narrative") or rec.get("body") or ""
        meta: MutableMapping[str, Any] = {"index": i}
        if id_field in rec:
            meta["id"] = rec[id_field]
        # Pass through common openFDA / ADE columns for audit without hardcoding drugs
        for k in ("drug", "drug_name", "ade", "reaction", "source"):
            if k in rec:
                meta[k] = rec[k]
        out.append(evaluate_ae_text(str(text), meta=meta, **kwargs))
    return out
