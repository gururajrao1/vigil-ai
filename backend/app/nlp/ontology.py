"""Product ontology layer — brand ↔ generic (INN) ↔ chemical expansion.

VigilAI already resolves a surface mention *inward* (brand → generic + ATC) in
``drug_norm``. Signal detection also needs the *outward* direction: given any
name, what is the full alias closure that should be pooled as one product?

Grounded on the terminology stack reviewed in Gómez-Pérez et al., "Ontologies in
Medicinal Chemistry" — RxNorm (brand ↔ ingredient links), ChEBI (chemical
entities), ATC (therapeutic/chemical classification) — reduced to the practical
subset VigilAI can run offline with zero API keys:

  * curated brand/generic tables already in ``lexicons`` + ``stage2_synonyms``
  * explicit INN/USAN dual groups (paracetamol ≡ acetaminophen) — the paper's
    "ontology matching" problem, solved by an authored crosswalk
  * curated chemical (IUPAC-style / ChEBI preferred) names for common products
  * optional RxNorm + ChEBI (OLS4) lookups, never required

Licensed resources (SNOMED-CT, live UMLS Metathesaurus, MedDRA) are NOT bundled;
event coding stays on the existing open MedDRA-style surrogate.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set

from ..config import settings
from .lexicons import BRAND_TO_GENERIC, DRUG_ATC, GENERIC_DRUGS, atc_for, normalize_drug

logger = logging.getLogger("vigilai.ontology")

# --------------------------------------------------------------------------- #
# Authored crosswalks
# --------------------------------------------------------------------------- #
# INN (WHO) / USAN dual names for the same ingredient. First element is the
# preferred storage label; WHO INN wins because ATC — our class backbone — is
# WHO-maintained, except where an older name is overwhelmingly dominant in the
# corpus (aspirin).
_INN_DUALS: tuple[tuple[str, ...], ...] = (
    ("paracetamol", "acetaminophen"),
    ("salbutamol", "albuterol"),
    ("aspirin", "acetylsalicylic acid", "acetyl salicylic acid"),
    ("adrenaline", "epinephrine"),
    ("noradrenaline", "norepinephrine"),
    ("glibenclamide", "glyburide"),
    ("furosemide", "frusemide"),
    ("lidocaine", "lignocaine"),
    ("ciclosporin", "cyclosporine", "cyclosporin"),
    ("rifampicin", "rifampin"),
    ("pethidine", "meperidine"),
    ("isoprenaline", "isoproterenol"),
    ("hydroxycarbamide", "hydroxyurea"),
    ("beclometasone", "beclomethasone"),
    ("amoxicillin", "amoxycillin"),
    ("metamizole", "dipyrone"),
)

# Chemical (IUPAC-style / ChEBI preferred) names — the third naming tier.
_CHEMICAL_NAMES: Dict[str, tuple[str, ...]] = {
    "paracetamol": ("n-(4-hydroxyphenyl)acetamide",),
    "ibuprofen": ("2-[4-(2-methylpropyl)phenyl]propanoic acid",),
    "aspirin": ("2-(acetyloxy)benzoic acid",),
    "naproxen": ("(2s)-2-(6-methoxynaphthalen-2-yl)propanoic acid",),
    "diclofenac": ("2-[2-(2,6-dichloroanilino)phenyl]acetic acid",),
    "metformin": ("1,1-dimethylbiguanide",),
    "warfarin": ("4-hydroxy-3-(3-oxo-1-phenylbutyl)-2h-chromen-2-one",),
    "tramadol": ("2-[(dimethylamino)methyl]-1-(3-methoxyphenyl)cyclohexan-1-ol",),
    "salbutamol": ("4-[2-(tert-butylamino)-1-hydroxyethyl]-2-(hydroxymethyl)phenol",),
    "omeprazole": (
        "5-methoxy-2-[(4-methoxy-3,5-dimethylpyridin-2-yl)methanesulfinyl]-1h-benzimidazole",
    ),
    "metoprolol": ("1-[4-(2-methoxyethyl)phenoxy]-3-[(propan-2-yl)amino]propan-2-ol",),
    "sertraline": (
        "(1s,4s)-4-(3,4-dichlorophenyl)-n-methyl-1,2,3,4-tetrahydronaphthalen-1-amine",
    ),
    "clopidogrel": (
        "methyl (2s)-2-(2-chlorophenyl)-2-(6,7-dihydrothieno[3,2-c]pyridin-5(4h)-yl)acetate",
    ),
}

# Only IDs we can assert offline with confidence; anything else stays None and
# can be filled by the optional ChEBI lookup.
_CHEBI_IDS: Dict[str, str] = {
    "paracetamol": "CHEBI:46195",
    "ibuprofen": "CHEBI:5855",
    "aspirin": "CHEBI:15365",
    "metformin": "CHEBI:6801",
}

# Alias keys that are storage noise rather than real names
_ALIAS_STOP = frozenset({"", "drug", "drugs", "tablet", "tablets", "mg"})
_DOSAGE_SUFFIXES = ("tablet", "tablets", "capsule", "capsules", "mg", "mcg", "ml",
                    "injection", "solution", "suspension", "cream", "gel")

_DUAL_TO_PREFERRED: Dict[str, str] = {}
_PREFERRED_TO_DUALS: Dict[str, tuple[str, ...]] = {}
for _group in _INN_DUALS:
    _preferred = _group[0]
    _PREFERRED_TO_DUALS[_preferred] = _group
    for _member in _group:
        _DUAL_TO_PREFERRED[_member] = _preferred

_BRANDS_BY_GENERIC: Dict[str, Set[str]] = {}
_INDEX_LOCK = threading.Lock()
_INDEX_READY = False
_CONCEPT_CACHE: Dict[str, "ProductConcept"] = {}
_CACHE_LOCK = threading.Lock()


def _clean(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _is_useful_alias(alias: str, canonical: str) -> bool:
    if alias in _ALIAS_STOP or alias == canonical:
        return False
    if len(alias) < 3 or alias.isdigit():
        return False
    if any(alias.endswith(sfx) and alias != sfx for sfx in _DOSAGE_SUFFIXES):
        return False
    return True


def _build_index() -> None:
    """Invert the brand→generic tables once, lazily."""
    global _INDEX_READY
    if _INDEX_READY:
        return
    with _INDEX_LOCK:
        if _INDEX_READY:
            return
        from .stage2_synonyms import PRODUCT_SYNONYMS

        index: Dict[str, Set[str]] = {}
        for brand, generic in BRAND_TO_GENERIC.items():
            b, g = _clean(brand), _clean(generic)
            if _is_useful_alias(b, g):
                index.setdefault(g, set()).add(b)
        for folded, canonical in PRODUCT_SYNONYMS.items():
            alias = _clean(folded)
            canon = _clean(canonical)
            if alias.isalpha() and _is_useful_alias(alias, canon):
                index.setdefault(canon, set()).add(alias)
        _BRANDS_BY_GENERIC.update(index)
        _INDEX_READY = True


def preferred_generic(generic: Optional[str]) -> str:
    """Collapse INN/USAN duals onto one storage label (acetaminophen → paracetamol)."""
    g = _clean(generic)
    return _DUAL_TO_PREFERRED.get(g, g)


def dual_names(generic: Optional[str]) -> tuple[str, ...]:
    return _PREFERRED_TO_DUALS.get(preferred_generic(generic), ())


def concept_id_for(preferred: str, atc: Optional[str], rxcui: Optional[str]) -> str:
    seed = f"{preferred}|{atc or rxcui or ''}"
    return "VIG-PC-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


@dataclass
class ProductConcept:
    """One product identity with its brand / generic / chemical name tiers."""

    concept_id: str
    preferred_generic: str
    surface: str = ""
    brands: List[str] = field(default_factory=list)
    generics: List[str] = field(default_factory=list)
    chemicals: List[str] = field(default_factory=list)
    atc: Optional[str] = None
    rxcui: Optional[str] = None
    chebi_id: Optional[str] = None
    sources: List[str] = field(default_factory=list)

    def aliases(self) -> List[str]:
        seen: List[str] = []
        for name in [self.preferred_generic, *self.generics, *self.brands, *self.chemicals]:
            if name and name not in seen:
                seen.append(name)
        return seen

    def to_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "preferred_generic": self.preferred_generic,
            "surface": self.surface,
            "brands": self.brands,
            "generics": self.generics,
            "chemicals": self.chemicals,
            "atc": self.atc,
            "rxcui": self.rxcui,
            "chebi_id": self.chebi_id,
            "sources": self.sources,
            "aliases": self.aliases(),
            "n_aliases": len(self.aliases()),
        }


def _offline_generic(surface: str) -> tuple[str, str]:
    """Return (generic, source) using offline maps only."""
    raw = _clean(surface)
    if not raw:
        return "", "empty"
    mapped = normalize_drug(raw)
    if mapped != raw:
        return mapped, "brand_map"
    try:
        from .stage2_synonyms import lookup_product_synonym

        syn = lookup_product_synonym(raw)
        if syn:
            return _clean(syn), "synonym_registry"
    except Exception:  # pragma: no cover - defensive
        logger.debug("stage2 synonym lookup failed for %r", raw, exc_info=True)
    if raw in GENERIC_DRUGS or raw in DRUG_ATC:
        return raw, "generic_lexicon"
    return raw, "verbatim"


def _rxnorm_aliases(surface: str) -> dict:
    """Optional RxNorm expansion (brand names, ingredients, synonyms). No key."""
    if not settings.use_rxnorm:
        return {}
    try:
        import httpx

        base = settings.rxnorm_base_url
        r = httpx.get(f"{base}/approximateTerm.json",
                      params={"term": surface, "maxEntries": 1}, timeout=4.0)
        if r.status_code != 200:
            return {}
        cands = r.json().get("approximateGroup", {}).get("candidate", []) or []
        rxcui = cands[0].get("rxcui") if cands else None
        if not rxcui:
            return {}
        r2 = httpx.get(f"{base}/rxcui/{rxcui}/related.json",
                       params={"tty": "IN+PIN+BN+SY"}, timeout=5.0)
        brands: Set[str] = set()
        generics: Set[str] = set()
        if r2.status_code == 200:
            for group in r2.json().get("relatedGroup", {}).get("conceptGroup", []) or []:
                tty = group.get("tty")
                for concept in group.get("conceptProperties", []) or []:
                    name = _clean(concept.get("name"))
                    if not name:
                        continue
                    if tty == "BN":
                        brands.add(name)
                    else:
                        generics.add(name)
        return {"rxcui": rxcui, "brands": brands, "generics": generics}
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("RxNorm alias lookup failed for %r: %s", surface, exc)
        return {}


def _chebi_lookup(generic: str) -> dict:
    """Optional ChEBI (via EBI OLS4) chemical-name lookup. No key."""
    if not settings.use_chebi or not generic:
        return {}
    try:
        import httpx

        r = httpx.get(
            f"{settings.chebi_base_url}/search",
            params={"q": generic, "ontology": "chebi", "rows": 1, "exact": "false"},
            timeout=5.0,
        )
        if r.status_code != 200:
            return {}
        docs = (r.json().get("response") or {}).get("docs") or []
        if not docs:
            return {}
        doc = docs[0]
        out: dict = {}
        obo_id = doc.get("obo_id") or doc.get("short_form")
        if obo_id:
            out["chebi_id"] = str(obo_id).replace("_", ":")
        label = _clean(doc.get("label"))
        if label and label != generic:
            out["chemicals"] = {label}
        return out
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("ChEBI lookup failed for %r: %s", generic, exc)
        return {}


def resolve_product(surface: str, *, online: bool = False) -> ProductConcept:
    """Resolve any product surface to its concept with full alias tiers.

    Offline by default so ingest and bulk analytics never block on the network.
    """
    raw = _clean(surface)
    cache_key = f"{raw}|{int(online)}"
    if raw and cache_key in _CONCEPT_CACHE:
        return _CONCEPT_CACHE[cache_key]

    _build_index()
    generic, source = _offline_generic(raw)
    preferred = preferred_generic(generic)
    sources = [source] if source not in ("empty",) else []

    members = set(dual_names(preferred)) or {preferred}
    members.discard("")

    brands: Set[str] = set()
    chemicals: Set[str] = set()
    atc: Optional[str] = None
    chebi_id: Optional[str] = None
    for member in members:
        brands |= _BRANDS_BY_GENERIC.get(member, set())
        chemicals |= set(_CHEMICAL_NAMES.get(member, ()))
        atc = atc or atc_for(member)
        chebi_id = chebi_id or _CHEBI_IDS.get(member)
    if chebi_id:
        sources.append("chebi_curated")

    rxcui: Optional[str] = None
    if online and preferred:
        rx = _rxnorm_aliases(raw or preferred)
        if rx:
            rxcui = rx.get("rxcui")
            brands |= rx.get("brands") or set()
            members |= {g for g in (rx.get("generics") or set()) if g}
            sources.append("rxnorm")
        if not chebi_id or not chemicals:
            chem = _chebi_lookup(preferred)
            if chem:
                chebi_id = chebi_id or chem.get("chebi_id")
                chemicals |= chem.get("chemicals") or set()
                sources.append("chebi_ols")

    # The surface itself is a valid alias when it is not already covered
    if raw and raw not in members and raw not in brands and _is_useful_alias(raw, preferred):
        brands.add(raw)

    concept = ProductConcept(
        concept_id=concept_id_for(preferred, atc, rxcui) if preferred else "",
        preferred_generic=preferred,
        surface=raw,
        brands=sorted(b for b in brands if b and b != preferred),
        generics=sorted(m for m in members if m and m != preferred),
        chemicals=sorted(chemicals),
        atc=atc,
        rxcui=rxcui,
        chebi_id=chebi_id,
        sources=sources,
    )
    if raw:
        with _CACHE_LOCK:
            _CONCEPT_CACHE[cache_key] = concept
    return concept


def expand_product(term: str, *, online: bool = False) -> dict:
    """Full alias closure for a product term, grouped by naming tier."""
    concept = resolve_product(term, online=online)
    return {
        **concept.to_dict(),
        "tiers": {
            "brand": concept.brands,
            "generic": [concept.preferred_generic, *concept.generics] if concept.preferred_generic else [],
            "chemical": concept.chemicals,
        },
    }


def aliases_for_product(term: str) -> FrozenSet[str]:
    """Lowercase alias closure used by analytics to pool synonymous products."""
    concept = resolve_product(term)
    if not concept.preferred_generic:
        return frozenset()
    return frozenset(concept.aliases())


def same_concept(left: str, right: str) -> bool:
    """True when two surfaces resolve to the same product concept."""
    a, b = _clean(left), _clean(right)
    if not a or not b:
        return False
    if a == b:
        return True
    ca, cb = resolve_product(a), resolve_product(b)
    if ca.concept_id and ca.concept_id == cb.concept_id:
        return True
    return bool(aliases_for_product(a) & aliases_for_product(b))


def clear_cache() -> None:
    """Drop memoized concepts (used by tests and label-cleanup routines)."""
    with _CACHE_LOCK:
        _CONCEPT_CACHE.clear()


def known_dual_groups() -> List[dict]:
    return [
        {"preferred": group[0], "alternates": list(group[1:])}
        for group in _INN_DUALS
    ]


def ontology_stack() -> List[str]:
    """Terminology provenance surfaced in API payloads and the handbook."""
    return [
        "RxNorm (brand ↔ ingredient ↔ synonym; NIH, keyless, optional)",
        "ChEBI via EBI OLS4 (chemical entity names; keyless, optional)",
        "WHO ATC (therapeutic/chemical class backbone)",
        "Curated INN/USAN dual crosswalk (offline ontology matching)",
        "MedDRA-style PT/SOC open surrogate for events (not licensed MedDRA)",
    ]


def iter_alias_pairs() -> Iterable[tuple[str, str]]:
    """(alias, preferred) pairs for offline diagnostics."""
    _build_index()
    for generic, brands in _BRANDS_BY_GENERIC.items():
        pref = preferred_generic(generic)
        for brand in sorted(brands):
            yield brand, pref
