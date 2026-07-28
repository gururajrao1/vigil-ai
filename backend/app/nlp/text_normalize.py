"""4-stage ingestion normalization orchestrator.

[1] Structural regex sanitization
[2] Synonym registry matching
[3] NER + CUI (Comprehend Medical–style; used on full paragraphs)
[4] Layman → MedDRA semantic embeddings (cosine ≥ 0.85)

Canonical storage:
  - Products → lowercase INN / device (PV convention)
  - Events → single MedDRA-style Preferred Term (Title Case)
"""
from __future__ import annotations

from typing import Optional

from .stage1_sanitize import (
    compress_spacing,
    fold_key,
    repair_scraped_text,
    sanitize_surface,
    strip_border_symbols,
)
from .stage2_synonyms import (
    lookup_event_synonym,
    lookup_product_synonym,
    lookup_region_synonym,
    resolve_synonym,
)

# Re-export fold helpers used across the codebase
__all__ = [
    "fold_key",
    "clean_whitespace",
    "title_case_pt",
    "canonical_event",
    "normalize_label",
    "normalize_ingest_fields",
    "normalize_ingest_fields_sync",
    "normalize_entity_surface",
    "dedupe_labels",
    "run_four_stage_event",
    "lookup_synonym",
    "lookup_event_synonym",
    "repair_scraped_text",
]

# Not clinical events on their own (transformer debris / generic words)
_JUNK_EVENTS = frozenset({
    "air", "aller", "flew", "harm", "heat", "inc", "ins", "int", "drop", "dust",
    "limp", "lost", "not", "ache", "dia", "par", "pal", "mig", "head", "loss",
    "mood", "moods", "thing", "stuff", "side", "effect", "effects", "symptom", "symptoms",
    "issue", "problem", "reaction", "better", "worse", "good", "bad", "ok",
    "bow", "cho", "gin", "gui", "hem", "iso", "mca", "mid", "oste", "pace",
    "per", "pit", "pts", "sar", "sept", "tend", "test", "arms", "ears", "feet",
    "legs", "lip", "back", "bone", "skin", "gum", "lung", "155",
    # English verbs / non-AE nouns the biomedical NER over-tags
    "call", "calls", "called", "calling", "thank", "thanks", "take", "takes",
    "taken", "taking", "took", "broke", "break", "breaks", "myth", "myths",
    "normal", "desire", "energy", "awake", "appointment", "changes", "change",
    "feelings", "feeling", "healthy", "invalid", "extension", "discharge",
    "discharged", "destroyed", "damage", "concentrate", "difficulty",
    "hunger", "scared", "crying", "tears", "tense", "tired", "sweaty", "sweat",
    "puffy", "shook", "spins", "stiff", "sores", "peeing", "anger", "cancer",
    "tumor", "tumour", "heart", "udeny", "drows", "febril", "hangover",
})

_SHORT_EVENT_OK = frozenset({
    "flu", "hiv", "ibs", "uti", "dvt", "pe", "mi", "cva", "gerd", "copd",
    "rash", "gout", "acne", "pain", "cold", "fever", "cough", "edema", "coma",
})


def clean_whitespace(value: str) -> str:
    return compress_spacing(value)


def title_case_pt(value: str) -> str:
    s = compress_spacing(value)
    if not s:
        return ""
    return " ".join(w[:1].upper() + w[1:].lower() if w else "" for w in s.split(" "))


def lookup_synonym(value: str) -> Optional[str]:
    return lookup_product_synonym(value) or lookup_region_synonym(value)


def run_four_stage_event(surface: str) -> Optional[dict]:
    """Full event path through stages 1→2→4 (stage 3 is paragraph-level NER).

    Medically strict: only returns a Preferred Term when ``map_term`` matches
    (or Stage-4 embedding lands on a matched PT). Never invents title-case junk
    like "Calls" / "Thanks" as fake clinical events.
    """
    from .lexicons import SYMPTOMS
    from .meddra import map_term
    from .stage4_meddra_embed import map_layman_to_meddra
    from .term_glossary import is_nonclinical_surface
    from .vernacular import VERNACULAR, vernacular_lookup

    # Stage 1
    san = sanitize_surface(surface)
    if not san.cleaned:
        return None

    if is_nonclinical_surface(san.cleaned):
        return None

    # Stage 2a — vernacular idioms (patient voice → lexicon surface)
    vern = vernacular_lookup(surface) or vernacular_lookup(san.cleaned) or VERNACULAR.get(san.cleaned.lower())
    # Stage 2b — synonym / plural / ADR cluster collapse
    syn = lookup_event_synonym(san.cleaned) or lookup_event_synonym(vern or "")
    raw = syn or vern or san.cleaned
    low = raw.lower()

    if low in _JUNK_EVENTS:
        return None
    if is_nonclinical_surface(raw):
        return None
    if len(low) < 4 and low not in _SHORT_EVENT_OK:
        return None
    if len(low) <= 4 and low not in _SHORT_EVENT_OK and low not in SYMPTOMS:
        if sum(1 for c in low if c in "aeiou") == 0:
            return None

    # Exact MedDRA surrogate map (surface or already-canonical PT name)
    term = map_term(low)
    if term.get("matched"):
        stage = "vernacular" if vern and not syn else ("synonym_or_exact" if (syn or vern) else "exact")
        return {**term, "stage": stage, "similarity": 1.0}

    # Lexicon symptom surfaces that map after synonym repair
    if low in SYMPTOMS:
        term2 = map_term(low)
        if term2.get("matched"):
            return {**term2, "stage": "lexicon", "similarity": 1.0}

    # Stage 4 — embedding / n-gram cosine ≥ 0.85 onto a *matched* PT only
    embedded = map_layman_to_meddra(raw)
    if embedded and embedded.get("matched") and embedded.get("pt"):
        check = map_term(embedded["pt"])
        if check.get("matched"):
            return {
                **check,
                "stage": embedded.get("method") or "embed",
                "similarity": embedded.get("similarity"),
                "matched_surface": embedded.get("matched_surface"),
            }

    # Hybrid fuzzy / lemma pass for novel phrasings on the stream
    from .hybrid_resolver import resolve_event

    hybrid = resolve_event(san.cleaned)
    if hybrid and hybrid.get("pt"):
        return hybrid

    # No fallback title-casing — unmatched layman text is dropped
    return None

def canonical_event(surface: str) -> Optional[str]:
    """Normalize an AE mention to one MedDRA-style PT, or None if junk.

    Device failure modes (IMDRF surrogates) are accepted verbatim when they match
    the offline device-failure lexicon — they are not MedDRA PTs.
    """
    raw = (surface or "").strip()
    if not raw:
        return None
    low = raw.lower()
    # Preserve already-coded IMDRF failure terms from extract_devices.
    try:
        from .devices import FAILURE_TO_IMDRF

        if low in FAILURE_TO_IMDRF:
            return (FAILURE_TO_IMDRF[low].get("term") or raw).strip()
        for meta in FAILURE_TO_IMDRF.values():
            term = (meta.get("term") or "").strip()
            if term and term.lower() == low:
                return term
    except Exception:
        pass

    result = run_four_stage_event(surface)
    if not result:
        return None
    return (result.get("pt") or "").strip() or None


def normalize_label(value: str, *, kind: str = "generic") -> str:
    """Clean + synonym-resolve before DB commit / filter use."""
    san = sanitize_surface(value)
    raw = san.cleaned
    if not raw:
        return ""

    if kind == "event":
        return canonical_event(raw) or ""

    if kind == "condition":
        from .condition_norm import canonical_condition

        return canonical_condition(raw) or ""

    syn = resolve_synonym(raw, kind=kind if kind in ("product", "region") else "generic")
    if syn:
        raw = syn

    if kind == "product":
        from .drug_norm import canonical_product

        return canonical_product(raw) or ""

    if kind == "region":
        if raw.lower() in {"global", "worldwide"}:
            return "Global"
        return title_case_pt(raw)

    return raw.lower()


async def normalize_ingest_fields(payload: dict) -> dict:
    return normalize_ingest_fields_sync(payload)


def normalize_ingest_fields_sync(payload: dict) -> dict:
    out = dict(payload or {})
    if out.get("body"):
        out["body"] = repair_scraped_text(str(out["body"]))
    if out.get("title"):
        out["title"] = repair_scraped_text(str(out["title"]))
    if out.get("region"):
        out["region"] = normalize_label(str(out["region"]), kind="region")
    if out.get("country"):
        out["country"] = normalize_label(str(out["country"]), kind="region")
    if out.get("drug"):
        out["drug"] = normalize_label(str(out["drug"]), kind="product")
    if out.get("symptom") or out.get("event"):
        key = "symptom" if out.get("symptom") else "event"
        out[key] = normalize_label(str(out[key]), kind="event")
    if out.get("platform"):
        out["platform"] = clean_whitespace(str(out["platform"])).lower()
    if out.get("news_source"):
        out["news_source"] = clean_whitespace(str(out["news_source"]))
    return out


def normalize_entity_surface(text: str, entity_kind: str) -> str:
    kind = "product" if entity_kind in ("drug", "device", "product") else (
        "event" if entity_kind in ("symptom", "event", "ae") else (
            "condition" if entity_kind in ("condition", "indication") else "generic"
        )
    )
    return normalize_label(text, kind=kind)


def dedupe_labels(labels: list[str], *, kind: str = "event") -> list[str]:
    """Collapse casing/synonym variants to one canonical label each."""
    by_fold: dict[str, str] = {}
    for lab in labels:
        canon = normalize_label(lab, kind=kind)
        if not canon:
            continue
        fk = fold_key(canon)
        if fk and fk not in by_fold:
            by_fold[fk] = canon
    return sorted(by_fold.values(), key=lambda x: x.lower())
