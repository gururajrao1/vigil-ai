"""Advanced multi-pass hybrid event resolver (in-memory stream stabilization).

Pass 1 — Morphological Jaccard (token n-grams) + RapidFuzz token-sort edit distance
         Combined score > 85% → collapse onto existing MedDRA-surrogate PT.
Pass 2 — SapBERT (or BioBERT / MiniLM) dense embeddings + Faiss ANN over the
         local vocabulary index for zero-character-overlap synonyms.
Pass 3 — spaCy / scispaCy contextual sequence re-ranking: conversational verbs
         get near-zero clinical relevance and are discarded; true phenotypes pass.

Offline-first: every pass degrades to a deterministic fallback when optional
packages (rapidfuzz, faiss, torch/transformers, spacy) are absent.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Optional

import numpy as np

from .meddra import map_term
from .stage1_sanitize import fold_key, sanitize_surface
from .stage2_synonyms import lookup_event_synonym
from .vernacular import vernacular_lookup

logger = logging.getLogger("vigilai.hybrid_resolver")

FUZZY_THRESHOLD = 85.0          # Pass 1 combined score (0–100)
VECTOR_THRESHOLD = 0.85         # Pass 2 cosine / ANN similarity
CLINICAL_RELEVANCE_MIN = 0.35   # Pass 3 minimum to keep a candidate

_LEMMA_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"ies$", re.I), "y"),
    (re.compile(r"(ises|izes)$", re.I), "ise"),
    (re.compile(r"ing$", re.I), ""),
    (re.compile(r"ed$", re.I), ""),
    (re.compile(r"es$", re.I), ""),
    (re.compile(r"s$", re.I), ""),
]

_MEDICAL_LEMMAS: dict[str, str] = {
    "vomits": "vomiting", "vomited": "vomiting", "vomiting": "vomiting",
    "nauseated": "nausea", "nauseous": "nausea",
    "headaches": "headache", "rashes": "rash", "seizures": "seizure",
    "dizzy": "dizziness", "dizzyness": "dizziness", "fatigued": "fatigue",
    "swollen": "swelling", "itched": "itching", "itchy": "itching",
    "bled": "bleeding", "bleeding": "bleeding",
    "pains": "pain", "ached": "pain", "aching": "pain",
}

# Zero-overlap / reorder aliases seeded into the catalog (Pass 1+2 targets)
_SEMANTIC_SEEDS: dict[str, str] = {
    "lou gehrigs disease": "amyotrophic lateral sclerosis",
    "lou gehrig's disease": "amyotrophic lateral sclerosis",
    "lou gehrig disease": "amyotrophic lateral sclerosis",
    "als": "amyotrophic lateral sclerosis",
    "motor neurone disease": "amyotrophic lateral sclerosis",
    "motor neuron disease": "amyotrophic lateral sclerosis",
    "failure of the liver acute": "liver damage",
    "acute failure of the liver": "liver damage",
    "acute liver failure": "liver damage",
    "liver failure acute": "liver damage",
    "failure of the liver": "liver damage",
    "heart attack": "myocardial infarction",
    "mi": "myocardial infarction",
    "high blood sugar": "hyperglycaemia",
    "low blood sugar": "hypoglycaemia",
    "brain zaps": "paresthesia",
    "pins and needles": "tingling",
}

_CONVERSATIONAL_POS = frozenset({"VERB", "AUX", "ADP", "DET", "PRON", "PART", "INTJ", "CCONJ", "SCONJ"})
_CLINICAL_POS_BOOST = frozenset({"NOUN", "PROPN", "ADJ"})


# --------------------------------------------------------------------------- #
# Lemmatization
# --------------------------------------------------------------------------- #
def lemmatize_medical(surface: str) -> str:
    raw = sanitize_surface(surface).cleaned.lower()
    if not raw:
        return ""
    if raw in _MEDICAL_LEMMAS:
        return _MEDICAL_LEMMAS[raw]
    parts = raw.split()
    if len(parts) == 1:
        tok = parts[0]
        if tok in _MEDICAL_LEMMAS:
            return _MEDICAL_LEMMAS[tok]
        for pat, repl in _LEMMA_RULES:
            if pat.search(tok) and len(tok) > 4:
                stem = pat.sub(repl, tok)
                if stem and map_term(stem).get("matched"):
                    return stem
                if stem in _MEDICAL_LEMMAS:
                    return _MEDICAL_LEMMAS[stem]
        return tok
    last = parts[-1]
    return " ".join(parts[:-1] + [lemmatize_medical(last) or last])


# --------------------------------------------------------------------------- #
# Vocabulary catalog (in-memory master strings)
# --------------------------------------------------------------------------- #
def _catalog_strings() -> list[tuple[str, str]]:
    from .meddra import _PT_MAP

    rows: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(surface: str, pt: str) -> None:
        key = surface.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        rows.append((key, pt))

    for surface, (pt, _) in _PT_MAP.items():
        _add(surface, pt)
        _add(pt.lower(), pt)
    for seed, target in _SEMANTIC_SEEDS.items():
        md = map_term(target)
        if md.get("matched"):
            _add(seed, md["pt"])
            _add(target, md["pt"])
    return rows


_CATALOG: list[tuple[str, str]] | None = None


def _get_catalog() -> list[tuple[str, str]]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = _catalog_strings()
    return _CATALOG


# Ensure ALS / MI style terms exist in MedDRA surrogate for Pass 2 acceptance
def _ensure_semantic_meddra() -> None:
    from . import meddra as md

    extras = {
        "amyotrophic lateral sclerosis": ("Amyotrophic lateral sclerosis", "NERV"),
        "als": ("Amyotrophic lateral sclerosis", "NERV"),
        "lou gehrig's disease": ("Amyotrophic lateral sclerosis", "NERV"),
        "lou gehrigs disease": ("Amyotrophic lateral sclerosis", "NERV"),
        "myocardial infarction": ("Myocardial infarction", "CARD"),
        "heart attack": ("Myocardial infarction", "CARD"),
        "hyperglycaemia": ("Hyperglycaemia", "METAB"),
        "hyperglycemia": ("Hyperglycaemia", "METAB"),
        "hypoglycaemia": ("Hypoglycaemia", "METAB"),
        "hypoglycemia": ("Hypoglycaemia", "METAB"),
    }
    for k, v in extras.items():
        if k not in md._PT_MAP:
            md._PT_MAP[k] = v
            md._PT_BY_NAME[v[0].lower()] = v
            md._PT_BY_NAME[k] = v


_ensure_semantic_meddra()


# --------------------------------------------------------------------------- #
# Pass 1 — Morphological Jaccard + edit-distance hybrid (RapidFuzz)
# --------------------------------------------------------------------------- #
def _char_ngrams(text: str, n: int = 3) -> set[str]:
    s = f"  {fold_key(text).lower()}  "
    if len(s) < n:
        return {s} if s.strip() else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


_STOP = frozenset({"of", "the", "a", "an", "and", "or", "to", "in", "on", "for", "with", "by"})


def _token_jaccard(a: str, b: str) -> float:
    """Token-level Jaccard (order-invariant) + light character n-gram blend."""
    def toks(s: str) -> set[str]:
        return {
            t for t in s.lower().replace("-", " ").replace(",", " ").split()
            if t and t not in _STOP
        }

    ta, tb = toks(a), toks(b)
    token_j = (len(ta & tb) / len(ta | tb)) if ta and tb else 0.0
    ga, gb = _char_ngrams(" ".join(sorted(ta))), _char_ngrams(" ".join(sorted(tb)))
    char_j = (len(ga & gb) / len(ga | gb)) if ga and gb else 0.0
    # Prefer token overlap for word-order rearrangements
    return 0.75 * token_j + 0.25 * char_j


def _combined_morph_score(query: str, candidate: str) -> dict[str, float]:
    """Two-part score: Jaccard overlap + token-sort edit distance (0–100)."""
    jaccard = _token_jaccard(query, candidate) * 100.0

    def _content(s: str) -> str:
        return " ".join(
            t for t in s.lower().replace("-", " ").replace(",", " ").split()
            if t and t not in _STOP
        )

    q_c, c_c = _content(query), _content(candidate)
    try:
        from rapidfuzz import fuzz  # type: ignore

        token_sort = float(fuzz.token_sort_ratio(q_c or query, c_c or candidate))
        token_set = float(fuzz.token_set_ratio(q_c or query, c_c or candidate))
        partial = float(fuzz.partial_ratio(query, candidate))
        edit = 0.5 * token_sort + 0.35 * token_set + 0.15 * partial
    except Exception:
        from difflib import SequenceMatcher

        qa = " ".join(sorted((q_c or query).split()))
        ca = " ".join(sorted((c_c or candidate).split()))
        edit = SequenceMatcher(None, qa, ca).ratio() * 100.0
        token_sort = edit
        token_set = edit
        partial = edit

    # Emphasize order-invariant token overlap for rearrangements
    combined = 0.50 * jaccard + 0.50 * edit
    return {
        "jaccard": round(jaccard, 2),
        "token_sort": round(token_sort, 2),
        "token_set": round(token_set, 2),
        "partial": round(partial, 2),
        "combined": round(combined, 2),
    }


def pass1_morphological(
    surface: str, *, threshold: float = FUZZY_THRESHOLD
) -> Optional[dict]:
    """Pass 1: neutralize word-order / spelling / plural drift against catalog."""
    query = sanitize_surface(surface).cleaned
    if not query:
        return None

    catalog = _get_catalog()
    surfaces = [s for s, _ in catalog]
    q = query.lower()

    # RapidFuzz extractOne is O(n) with C-speed scorer — avoid Python double-loop.
    try:
        from rapidfuzz import fuzz, process

        hit = process.extractOne(
            q,
            surfaces,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )
        if not hit:
            return None
        cand_surface, score, idx = hit
        pt = catalog[idx][1]
        scores = _combined_morph_score(q, cand_surface)
        # Prefer combined morph when available; fall back to token_sort score
        combined = max(float(score), float(scores["combined"]))
        if combined < threshold:
            return None
        term = map_term(pt)
        if not term.get("matched"):
            term = map_term(cand_surface)
        if not term.get("matched"):
            return None
        return {
            **term,
            "stage": "pass1_morph_jaccard_edit",
            "method": "pass1_morph_jaccard_edit",
            "similarity": round(combined / 100.0, 4),
            "matched_surface": cand_surface,
            "morph_scores": scores,
        }
    except Exception:
        pass

    best: Optional[dict] = None
    best_score = -1.0
    for cand_surface, pt in catalog:
        scores = _combined_morph_score(q, cand_surface)
        if scores["combined"] > best_score:
            best_score = scores["combined"]
            term = map_term(pt)
            if not term.get("matched"):
                term = map_term(cand_surface)
            if not term.get("matched"):
                continue
            best = {
                **term,
                "stage": "pass1_morph_jaccard_edit",
                "method": "pass1_morph_jaccard_edit",
                "similarity": round(scores["combined"] / 100.0, 4),
                "matched_surface": cand_surface,
                "morph_scores": scores,
            }

    if best and best_score >= threshold:
        return best
    return None


# --------------------------------------------------------------------------- #
# Pass 2 — SapBERT / BioBERT + Faiss ANN (offline fallbacks)
# --------------------------------------------------------------------------- #
class _SapBertFaissIndex:
    """Local ANN over MedDRA-surrogate vocabulary using SapBERT when available."""

    def __init__(self) -> None:
        self.catalog = _get_catalog()
        self.surfaces = [s for s, _ in self.catalog]
        self.pts = [p for _, p in self.catalog]
        self.backend = "none"
        self._encode = None
        self._index = None
        self._matrix = None
        self._build()

    def _build(self) -> None:
        vectors = None
        # Heavy encoders only if already cached locally — never block ingest on download.
        import os

        allow_download = os.getenv("VIGILAI_ALLOW_EMBED_DOWNLOAD", "").strip() in {"1", "true", "yes"}
        for model_name, label in (
            ("cambridgeltl/SapBERT-from-PubMedBERT-fulltext", "sapbert"),
            ("pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb", "biobert"),
            ("sentence-transformers/all-MiniLM-L6-v2", "minilm"),
        ):
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(model_name, local_files_only=not allow_download)
                vectors = model.encode(
                    self.surfaces, normalize_embeddings=True, show_progress_bar=False
                )
                self._encode = lambda texts, m=model: m.encode(
                    texts, normalize_embeddings=True, show_progress_bar=False
                )
                self.backend = label
                logger.info("hybrid Pass2 encoder: %s", label)
                break
            except Exception as exc:
                logger.debug("Pass2 encoder %s unavailable: %s", label, exc)

        if vectors is None:
            # Deterministic char n-gram bag embeddings (always available, offline)
            vectors = np.vstack([self._ngram_vec(s) for s in self.surfaces])
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors = vectors / norms
            self._encode = lambda texts: np.vstack([self._ngram_vec(t) for t in texts])
            self.backend = "ngram"
            logger.info("hybrid Pass2 encoder: ngram fallback")

        self._matrix = np.asarray(vectors, dtype=np.float32)

        try:
            import faiss  # type: ignore

            dim = self._matrix.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(self._matrix)
            self._index = index
            self.backend = f"{self.backend}+faiss"
        except Exception as exc:
            logger.debug("Faiss unavailable (%s); using numpy argmax ANN", exc)
            self._index = None

    @staticmethod
    def _ngram_vec(text: str, dim: int = 256) -> np.ndarray:
        vec = np.zeros(dim, dtype=np.float32)
        grams = _char_ngrams(text, 3)
        for g in grams:
            vec[hash(g) % dim] += 1.0
        n = float(np.linalg.norm(vec)) or 1.0
        return vec / n

    def query(self, text: str, threshold: float = VECTOR_THRESHOLD) -> Optional[dict]:
        if self._encode is None or self._matrix is None:
            return None
        q = np.asarray(self._encode([text]), dtype=np.float32)
        if q.ndim == 1:
            q = q.reshape(1, -1)
        # normalize
        qn = float(np.linalg.norm(q[0])) or 1.0
        q = q / qn

        if self._index is not None:
            scores, idxs = self._index.search(q, 1)
            score = float(scores[0][0])
            idx = int(idxs[0][0])
        else:
            sims = self._matrix @ q[0]
            idx = int(np.argmax(sims))
            score = float(sims[idx])

        if score < threshold or idx < 0:
            return None
        pt = self.pts[idx]
        term = map_term(pt)
        if not term.get("matched"):
            term = map_term(self.surfaces[idx])
        if not term.get("matched"):
            return None
        return {
            **term,
            "stage": f"pass2_{self.backend}",
            "method": f"pass2_{self.backend}",
            "similarity": round(score, 4),
            "matched_surface": self.surfaces[idx],
        }


_PASS2_INDEX: _SapBertFaissIndex | None = None


def _get_pass2_index() -> _SapBertFaissIndex:
    global _PASS2_INDEX
    if _PASS2_INDEX is None:
        _PASS2_INDEX = _SapBertFaissIndex()
    return _PASS2_INDEX


def pass2_sapbert_ann(
    surface: str, *, threshold: float = VECTOR_THRESHOLD
) -> Optional[dict]:
    """Pass 2: dense biomedical embedding + Faiss ANN against vocabulary."""
    query = sanitize_surface(surface).cleaned
    if not query:
        return None
    # Seeded zero-overlap synonyms first (instant, offline)
    key = query.lower()
    if key in _SEMANTIC_SEEDS:
        md = map_term(_SEMANTIC_SEEDS[key])
        if md.get("matched"):
            return {
                **md,
                "stage": "pass2_semantic_seed",
                "method": "pass2_semantic_seed",
                "similarity": 1.0,
                "matched_surface": key,
            }
    return _get_pass2_index().query(query, threshold=threshold)


# --------------------------------------------------------------------------- #
# Pass 3 — Contextual sequence candidate re-ranking (spaCy / scispaCy)
# --------------------------------------------------------------------------- #
_NLP = None
_NLP_TRIED = False


def _get_spacy():
    global _NLP, _NLP_TRIED
    if _NLP_TRIED:
        return _NLP
    _NLP_TRIED = True
    try:
        import spacy  # type: ignore

        for name in ("en_core_sci_sm", "en_core_web_sm", "en_core_web_md"):
            try:
                _NLP = spacy.load(name)
                logger.info("hybrid Pass3 spaCy model: %s", name)
                return _NLP
            except Exception:
                continue
    except Exception as exc:
        logger.debug("spaCy unavailable for Pass3: %s", exc)
    _NLP = False
    return _NLP


_CONVERSATIONAL_FILLERS = frozenset({
    "call", "calls", "called", "calling", "say", "says", "said", "saying",
    "post", "posts", "posted", "posting", "tell", "tells", "told",
    "ask", "asks", "asked", "write", "writes", "wrote", "read", "reads",
    "share", "shares", "shared", "think", "thinks", "thought",
    "want", "wants", "wanted", "need", "needs", "needed", "try", "tries", "tried",
    "take", "takes", "took", "taken", "get", "gets", "got", "make", "makes", "made",
    "go", "goes", "went", "come", "comes", "came", "thank", "thanks", "please",
    "help", "helped", "helps",
})


def clinical_relevance_score(
    surface: str,
    *,
    context: str = "",
    start: int | None = None,
    end: int | None = None,
) -> dict[str, Any]:
    """Assign a clinical relevance weight using POS / sequence context.

    Conversational filler verbs (calls, said, posted) → near-zero.
    Noun/adj medical phenotypes in symptom-like syntax → high weight.
    """
    low = (surface or "").strip().lower()
    if not low:
        return {"score": 0.0, "reason": "empty", "pos": None}

    from .term_glossary import is_nonclinical_surface

    if low in _CONVERSATIONAL_FILLERS or is_nonclinical_surface(low):
        return {"score": 0.02, "reason": "conversational_or_nonclinical", "pos": "VERB"}

    # Known MedDRA / vernacular hit → strong prior
    if map_term(low).get("matched") or vernacular_lookup(low) or lookup_event_synonym(low):
        base = 0.85
    else:
        base = 0.4

    nlp = _get_spacy()
    pos = None
    if nlp:
        snippet = context or surface
        if context and start is not None and end is not None:
            snippet = context[max(0, start - 48) : min(len(context), end + 48)]
        doc = nlp(snippet)
        surface_doc = nlp(surface)
        if surface_doc:
            pos = surface_doc[0].pos_
            if pos in _CONVERSATIONAL_POS and len(surface.split()) == 1:
                if not map_term(lemmatize_medical(low)).get("matched"):
                    return {"score": 0.05, "reason": "pos_conversational_verb", "pos": pos}
            if pos in _CLINICAL_POS_BOOST:
                base = min(1.0, base + 0.15)
            for tok in doc:
                if tok.text.lower() in low or low in tok.text.lower():
                    if tok.dep_ in {"nsubj", "dobj", "attr", "ROOT"} and tok.pos_ in _CLINICAL_POS_BOOST:
                        base = min(1.0, base + 0.1)
                    if tok.head.text.lower() in {"no", "not", "without"}:
                        base *= 0.15
                    break
    else:
        if len(low.split()) == 1 and low.endswith(("ed", "ing")) and not map_term(low).get("matched"):
            if not map_term(lemmatize_medical(low)).get("matched"):
                base = min(base, 0.15)
                pos = "VERB?"

    return {"score": round(base, 4), "reason": "contextual", "pos": pos}


def pass3_rerank(
    candidates: list[dict],
    *,
    surface: str,
    context: str = "",
    start: int | None = None,
    end: int | None = None,
) -> Optional[dict]:
    """Re-rank resolver candidates by clinical relevance; drop near-zero scores."""
    rel = clinical_relevance_score(surface, context=context, start=start, end=end)
    if rel["score"] < CLINICAL_RELEVANCE_MIN:
        return None

    if not candidates:
        return None

    scored = []
    for c in candidates:
        sim = float(c.get("similarity") or 0)
        combined = 0.6 * sim + 0.4 * rel["score"]
        row = dict(c)
        row["clinical_relevance"] = rel["score"]
        row["rerank_score"] = round(combined, 4)
        row["stage"] = f"{c.get('stage', 'unknown')}+pass3_rerank"
        scored.append(row)
    scored.sort(key=lambda r: r["rerank_score"], reverse=True)
    top = scored[0]
    if top["rerank_score"] < CLINICAL_RELEVANCE_MIN:
        return None
    return top


# --------------------------------------------------------------------------- #
# Public entrypoints
# --------------------------------------------------------------------------- #
def resolve_event(
    surface: str,
    *,
    context: str = "",
    start: int | None = None,
    end: int | None = None,
) -> Optional[dict]:
    """Run Pass 1 → Pass 2 → Pass 3 on an incoming stream surface (in-memory)."""
    if not surface:
        return None

    # Pass 3 early reject for conversational filler
    rel = clinical_relevance_score(surface, context=context, start=start, end=end)
    if rel["score"] < CLINICAL_RELEVANCE_MIN:
        return None

    lemma = lemmatize_medical(surface) or surface
    alias_key = " ".join(sanitize_surface(surface).cleaned.lower().replace(",", " ").split())
    seed = _SEMANTIC_SEEDS.get(alias_key) or _SEMANTIC_SEEDS.get(lemma)

    vern = vernacular_lookup(surface) or vernacular_lookup(lemma)
    syn = (
        lookup_event_synonym(surface)
        or lookup_event_synonym(lemma)
        or lookup_event_synonym(vern or "")
        or lookup_event_synonym(seed or "")
    )
    candidate = syn or vern or seed or lemma

    candidates: list[dict] = []

    exact = map_term(candidate)
    if exact.get("matched"):
        candidates.append({
            **exact,
            "stage": "exact_or_synonym",
            "method": "exact_or_synonym",
            "similarity": 1.0,
            "matched_surface": candidate,
        })

    # Pass 1 — morphological hybrid
    morph = pass1_morphological(surface)
    if morph:
        candidates.append(morph)
    if candidate != sanitize_surface(surface).cleaned.lower():
        morph2 = pass1_morphological(candidate)
        if morph2:
            candidates.append(morph2)

    # Pass 2 — only if Pass 1 did not already clear the threshold strongly
    strong_morph = any(
        (c.get("similarity") or 0) >= (FUZZY_THRESHOLD / 100.0)
        and str(c.get("stage", "")).startswith("pass1")
        for c in candidates
    )
    if not strong_morph:
        vec = pass2_sapbert_ann(surface)
        if vec:
            candidates.append(vec)
        if candidate != surface:
            vec2 = pass2_sapbert_ann(candidate)
            if vec2:
                candidates.append(vec2)

    if not candidates:
        return None

    # Pass 3 — contextual re-rank / discard
    return pass3_rerank(
        candidates, surface=surface, context=context, start=start, end=end
    )


def resolver_status() -> dict[str, Any]:
    """Diagnostics for /health or admin panels — resolver + ingest dedupe telemetry."""
    from .content_dedupe import get_dedupe_telemetry

    idx = _get_pass2_index()
    nlp = _get_spacy()
    dedupe = get_dedupe_telemetry()
    return {
        "pass1": "rapidfuzz+jaccard" if _rapidfuzz_available() else "difflib+jaccard",
        "pass2_backend": idx.backend,
        "pass2_catalog_size": len(idx.surfaces),
        "pass3_spacy": bool(nlp),
        "fuzzy_threshold": FUZZY_THRESHOLD,
        "vector_threshold": VECTOR_THRESHOLD,
        "clinical_relevance_min": CLINICAL_RELEVANCE_MIN,
        "total_scraped_records": dedupe["total_scraped_records"],
        "suppressed_duplicate_records": dedupe["suppressed_duplicate_records"],
        "clean_committed_records": dedupe["clean_committed_records"],
        "last_ingest_batch": dedupe["last_batch"],
        "content_dedupe": {
            "enabled": True,
            "algorithm": "sha256",
            "normalize": "casefold+strip_punct+collapse_ws",
            **dedupe,
        },
    }


def _rapidfuzz_available() -> bool:
    try:
        import rapidfuzz  # noqa: F401
        return True
    except Exception:
        return False
