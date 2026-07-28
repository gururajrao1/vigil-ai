"""Clinical entity extraction: drugs, symptoms, conditions (worldwide).

Two-tier, offline-first:
  * Lexicon + phrase matching (deterministic) — high precision, no dependencies.
  * Transformer biomedical NER (optional) — high recall across ANY region/brand.

Both tiers are merged and de-duplicated. Drugs are normalized to a generic (INN)
name + WHO ATC class; symptoms are standardized to a MedDRA-style Preferred Term
+ System Organ Class. The surface form is always preserved for traceability.
"""
from __future__ import annotations

import re
from typing import Dict, List

from .devices import AMBIGUOUS_BARE_PRODUCTS, extract_devices, is_known_device
from .drug_norm import normalize as normalize_drug_full
from .lexicons import (
    BRAND_TO_GENERIC,
    CONDITIONS,
    GENERIC_DRUGS,
    NON_MEDICAL_STOP,
    SYMPTOMS,
)
from .meddra import map_term
from .text_normalize import normalize_entity_surface, normalize_label
from .transformer_ner import extract_entities_transformer
from .vernacular import scan as scan_vernacular


def _build_matcher(terms: set[str]) -> re.Pattern:
    ordered = sorted(terms, key=len, reverse=True)
    escaped = [re.escape(t) for t in ordered]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


_DRUG_TERMS = set(GENERIC_DRUGS) | set(BRAND_TO_GENERIC.keys())
_DRUG_RE = _build_matcher(_DRUG_TERMS)
_SYMPTOM_RE = _build_matcher(SYMPTOMS)
_CONDITION_RE = _build_matcher(CONDITIONS)


def _enrich_drug(surface: str, start: int, end: int, source: str) -> dict:
    cleaned = normalize_entity_surface(surface, "drug") or surface
    info = normalize_drug_full(cleaned)
    generic = info["generic"] or cleaned.strip().lower()
    return {
        "text": surface,
        "normalized": generic,
        "generic": info["generic"] or generic,
        "atc": info.get("atc"),
        "rxcui": info.get("rxcui"),
        "start": start,
        "end": end,
        "source": source,
    }


def _enrich_symptom(surface: str, start: int, end: int, source: str) -> dict | None:
    from .stage3_ner_cui import assign_cui
    from .text_normalize import run_four_stage_event

    result = run_four_stage_event(surface)
    if not result or not result.get("pt"):
        return None
    pt = result["pt"]
    low = pt.lower()
    if low in NON_MEDICAL_STOP:
        return None
    term = map_term(low) if not result.get("soc") else result
    row = {
        "text": surface,
        "normalized": (term.get("pt") or pt).lower(),
        "pt": term.get("pt") or pt,
        "soc": term.get("soc"),
        "soc_code": term.get("soc_code"),
        "start": start,
        "end": end,
        "source": source,
        "norm_stage": result.get("stage"),
        "similarity": result.get("similarity"),
    }
    row["cui"] = assign_cui(kind="event", surface=surface, normalized=row["normalized"], pt=row["pt"])
    return row


def _dedupe(spans: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for s in spans:
        key = (s["normalized"], s.get("start"))
        if key not in seen and s["normalized"]:
            seen.add(key)
            out.append(s)
    return out


def _lexicon_pass(text: str) -> Dict[str, List[dict]]:
    drugs, symptoms, conditions = [], [], []
    for m in _DRUG_RE.finditer(text):
        drugs.append(_enrich_drug(m.group(0), m.start(), m.end(), "lexicon"))
    for m in _SYMPTOM_RE.finditer(text):
        s = _enrich_symptom(m.group(0), m.start(), m.end(), "lexicon")
        if s:
            symptoms.append(s)
    for m in _CONDITION_RE.finditer(text):
        # Prefer AE/symptom coding when the same surface is also a symptom lexicon hit
        # (e.g. "allergy" is both an indication and a Hypersensitivity PT).
        surface = m.group(0)
        as_sym = _enrich_symptom(surface, m.start(), m.end(), "lexicon")
        if as_sym:
            symptoms.append(as_sym)
            continue
        from .condition_norm import canonical_condition

        canon = canonical_condition(surface)
        if not canon:
            continue
        conditions.append({
            "text": surface,
            "normalized": canon,
            "start": m.start(),
            "end": m.end(),
            "source": "lexicon",
        })
    # Medical devices: products join the drug/product bucket, failure modes join
    # the symptom bucket, so the AE gates + disproportionality engine work unchanged.
    dev = extract_devices(text)
    if dev["products"]:
        # Drop drug-lexicon hits that fall inside a device span (e.g. "insulin"
        # inside "insulin pump") so the device is the product, not its sub-token.
        # Also drop bare ambiguous fragments (glucose/insulin) when a device is present.
        dev_spans = [(p["start"], p["end"]) for p in dev["products"]]
        drugs = [
            d for d in drugs
            if not any(s <= d["start"] < e for s, e in dev_spans)
            and (d.get("normalized") or "").strip().lower() not in AMBIGUOUS_BARE_PRODUCTS
        ]
    else:
        # Never treat bare "glucose" as a drug product (lab analyte, not a therapeutic).
        drugs = [
            d for d in drugs
            if (d.get("normalized") or "").strip().lower() != "glucose"
        ]
    # Promote lexicon/transformer hits that are known devices (IUD, catheter, …).
    promoted = []
    for d in drugs:
        canon = (d.get("normalized") or d.get("generic") or d.get("text") or "").strip().lower()
        if is_known_device(canon) or d.get("is_device") or d.get("product_type") == "device":
            d = {**d, "is_device": True, "product_type": "device", "atc": None}
            if not d.get("gmdn"):
                from .devices import DEVICE_GMDN, canonical_device
                meta = DEVICE_GMDN.get(canonical_device(canon), {})
                d["gmdn"] = meta.get("gmdn")
                d["device_class"] = meta.get("class")
                d["normalized"] = canonical_device(canon)
                d["generic"] = d["normalized"]
        promoted.append(d)
    drugs = promoted
    drugs.extend(dev["products"])
    symptoms.extend(dev["failures"])
    return {"drugs": drugs, "symptoms": symptoms, "conditions": conditions}


def _vernacular_pass(text: str) -> Dict[str, List[dict]]:
    """Map colloquial patient phrases to standardized symptom entities.

    Each match keeps the original ``phrase`` and ``source='vernacular'`` so the UI
    can show "we understood the patient's own words" for traceability.
    """
    from .stage3_ner_cui import assign_cui
    from .text_normalize import run_four_stage_event

    symptoms: List[dict] = []
    for v in scan_vernacular(text):
        result = run_four_stage_event(v["canonical"]) or run_four_stage_event(v["phrase"])
        if not result or not result.get("pt"):
            term = map_term(v["canonical"])
            pt = term["pt"]
            soc = term["soc"]
            soc_code = term["soc_code"]
        else:
            pt = result["pt"]
            soc = result.get("soc")
            soc_code = result.get("soc_code")
            if not soc:
                term = map_term(pt)
                soc, soc_code = term["soc"], term["soc_code"]
        row = {
            "text": v["phrase"],
            "normalized": pt.lower(),
            "pt": pt,
            "soc": soc,
            "soc_code": soc_code,
            "start": v["start"],
            "end": v["end"],
            "source": "vernacular",
            "phrase": v["phrase"],
            "norm_stage": (result or {}).get("stage", "vernacular"),
            "similarity": (result or {}).get("similarity"),
        }
        row["cui"] = assign_cui(kind="event", surface=v["phrase"], normalized=row["normalized"], pt=pt)
        symptoms.append(row)
    return {"drugs": [], "symptoms": symptoms, "conditions": []}


def _merge(base: Dict[str, List[dict]], extra: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
    for bucket in ("drugs", "symptoms", "conditions"):
        have = {e["normalized"] for e in base[bucket]}
        for e in extra.get(bucket, []):
            if e["normalized"] and e["normalized"] not in have:
                base[bucket].append(e)
                have.add(e["normalized"])
    return base


def extract_entities(text: str, use_transformer: bool | None = None) -> Dict[str, List[dict]]:
    """Return {'drugs': [...], 'symptoms': [...], 'conditions': [...]}.

    Runs inside the 4-stage normalization pipeline:
      Stage 1–2 applied per surface in ``_enrich_*``;
      Stage 3 = lexicon + vernacular + optional transformer NER + CUI;
      Stage 4 = embedding MedDRA map for unmatched layman phrases.

    ``use_transformer`` controls the (CPU-heavy) transformer tier:
      * None  -> follow the global ``USE_TRANSFORMER_NER`` setting (default).
      * True  -> force the transformer tier on (best recall for novel/global terms).
      * False -> lexicon-only (instant); used for bulk ingest of lexicon-derived
                 corpora where the transformer adds latency but no new entities.
    The lexicon tier always runs, so results never regress below deterministic.
    """
    if not text:
        return {"drugs": [], "symptoms": [], "conditions": []}

    from .stage1_sanitize import sanitize_surface
    from .stage3_ner_cui import assign_cui, merge_by_cui

    cleaned = sanitize_surface(text).cleaned or text
    result = _lexicon_pass(cleaned)

    # Vernacular tier: map patient slang/idioms to standardized PTs. Merged with
    # dedupe-by-normalized so it only adds symptoms the lexicon missed (no
    # double-counting of a PT already found literally).
    result = _merge(result, _vernacular_pass(cleaned))

    # Transformer tier (recall for global/unknown terms), enriched + merged.
    tf = extract_entities_transformer(cleaned) if use_transformer is not False else None
    if tf:
        enriched = {"drugs": [], "symptoms": [], "conditions": []}
        for d in tf.get("drugs", []):
            enriched["drugs"].append(
                _enrich_drug(d["text"], d["start"], d["end"], "transformer"))
        for s in tf.get("symptoms", []):
            es = _enrich_symptom(s["text"], s["start"], s["end"], "transformer")
            if es:
                enriched["symptoms"].append(es)
        for c in tf.get("conditions", []):
            from .condition_norm import canonical_condition

            canon = canonical_condition(c.get("text") or c.get("normalized") or "")
            if not canon:
                continue
            enriched["conditions"].append({
                "text": c["text"],
                "normalized": canon,
                "start": c["start"],
                "end": c["end"],
                "source": "transformer",
                "cui": assign_cui(kind="event", surface=c["text"], normalized=canon),
            })
        result = _merge(result, enriched)

    # Ensure every drug span carries a CUI (lexicon path)
    for d in result["drugs"]:
        if "cui" not in d:
            d["cui"] = assign_cui(
                kind="device" if d.get("product_type") == "device" else "drug",
                surface=d.get("text") or "",
                normalized=d.get("normalized") or "",
                rxcui=d.get("rxcui"),
            )

    merged = merge_by_cui({
        "drugs": _dedupe(result["drugs"]),
        "symptoms": _dedupe(result["symptoms"]),
        "conditions": _dedupe(result["conditions"]),
    })
    return merged
