"""Drug verbatim → RxNorm-style ingredient → ATC L1–L5 → ChEBI structure.

Ingredient resolution delegates to ``app.nlp.ontology.resolve_product`` (brand
tables, INN/USAN duals, optional keyless RxNorm) so there is one canonicalisation
path in the product. This module adds the ATC ladder, the chemical structure
layer, and a structural-similarity helper for class/chemistry read-across.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..lexicons import BRAND_TO_GENERIC, DRUG_ATC, GENERIC_DRUGS
from ..ontology import resolve_product
from . import crosswalk, dictionary_store
from .models import AtcLevel, AuditStamp, ChemicalStructure, DrugChemicalMap, SimilarDrug


def _clean(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _audit(online: bool) -> AuditStamp:
    return AuditStamp(
        source="atc_chebi_surrogate",
        online_enrichment=online,
        dictionaries=[
            "atc_tree_surrogate.json",
            "chebi_smiles_surrogate.json",
            "app.nlp.ontology",
        ],
    )


# --------------------------------------------------------------------------- #
# ATC ladder
# --------------------------------------------------------------------------- #
_LEVEL_SPANS: Tuple[Tuple[int, int], ...] = ((1, 1), (2, 3), (3, 4), (4, 5), (5, 7))


def atc_levels(atc_code: Optional[str]) -> List[AtcLevel]:
    """Split a WHO ATC code into its five nested levels with surrogate labels."""
    code = (atc_code or "").strip().upper()
    if not code:
        return []
    tree = dictionary_store.atc_tree()
    labels: Dict[str, Dict[str, str]] = tree.get("levels", {})
    level_names: Dict[str, str] = tree.get("level_names", {})

    out: List[AtcLevel] = []
    for level, width in _LEVEL_SPANS:
        if len(code) < width:
            break
        chunk = code[:width]
        if level == 5:
            label = f"Chemical substance {chunk}"
        else:
            label = (labels.get(str(level), {}) or {}).get(chunk) or f"ATC group {chunk}"
        out.append(AtcLevel(
            level=level,
            code=chunk,
            label=label,
            level_name=level_names.get(str(level), f"Level {level}"),
        ))
    return out


def atc_class_members(atc_prefix: str) -> List[str]:
    """Generic ingredients sharing an ATC prefix — the class read-across cohort."""
    prefix = (atc_prefix or "").strip().upper()
    if not prefix:
        return []
    return sorted({
        generic for generic, code in DRUG_ATC.items()
        if (code or "").upper().startswith(prefix)
    })


# --------------------------------------------------------------------------- #
# Chemical structure + similarity
# --------------------------------------------------------------------------- #
def chemical_for(generic: str) -> Optional[ChemicalStructure]:
    row = dictionary_store.chebi_table().get(_clean(generic))
    if not row:
        return None
    return ChemicalStructure(
        chebi_id=row.get("chebi_id"),
        smiles=row.get("smiles"),
        formula=row.get("formula"),
        is_macromolecule=bool(row.get("is_macromolecule")),
    )


def _ngrams(smiles: str, n: int = 3) -> Set[str]:
    s = (smiles or "").strip()
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _rdkit_tanimoto(left: str, right: str) -> Optional[float]:
    try:  # pragma: no cover - optional dependency
        from rdkit import Chem  # noqa: PLC0415
        from rdkit.Chem import AllChem, DataStructs  # noqa: PLC0415

        ma, mb = Chem.MolFromSmiles(left), Chem.MolFromSmiles(right)
        if ma is None or mb is None:
            return None
        fa = AllChem.GetMorganFingerprintAsBitVect(ma, 2, nBits=2048)
        fb = AllChem.GetMorganFingerprintAsBitVect(mb, 2, nBits=2048)
        return float(DataStructs.TanimotoSimilarity(fa, fb))
    except Exception:
        return None


def tanimoto(left_smiles: Optional[str], right_smiles: Optional[str]) -> Tuple[float, str]:
    """Structural similarity in [0,1] plus the method used.

    RDKit ECFP4 when the optional dependency is installed; otherwise a
    deterministic SMILES character-3-gram Jaccard surrogate. The surrogate ranks
    chemically related molecules sensibly for demo-scale read-across but is not a
    substitute for a real fingerprint.
    """
    if not left_smiles or not right_smiles:
        return 0.0, "unavailable"
    exact = _rdkit_tanimoto(left_smiles, right_smiles)
    if exact is not None:
        return round(exact, 3), "rdkit_morgan_ecfp4"
    a, b = _ngrams(left_smiles), _ngrams(right_smiles)
    if not a or not b:
        return 0.0, "unavailable"
    return round(len(a & b) / len(a | b), 3), "smiles_ngram_surrogate"


def similar_drugs(
    generic: str,
    candidates: Optional[Sequence[str]] = None,
    *,
    top_n: int = 5,
    min_score: float = 0.15,
) -> List[SimilarDrug]:
    """Rank structurally similar ingredients from the ChEBI surrogate subset."""
    base = chemical_for(generic)
    if not base or not base.smiles:
        return []
    table = dictionary_store.chebi_table()
    pool = [_clean(c) for c in candidates] if candidates else list(table.keys())

    scored: List[SimilarDrug] = []
    for name in pool:
        if name == _clean(generic):
            continue
        row = table.get(name)
        if not row or not row.get("smiles"):
            continue
        score, method = tanimoto(base.smiles, row["smiles"])
        if score >= min_score:
            scored.append(SimilarDrug(generic=name, tanimoto=score, method=method,
                                      chebi_id=row.get("chebi_id")))
    scored.sort(key=lambda s: s.tanimoto, reverse=True)
    return scored[:top_n]


# --------------------------------------------------------------------------- #
# Public mapper
# --------------------------------------------------------------------------- #
def is_known_drug(term: str) -> bool:
    key = _clean(term)
    if not key:
        return False
    if key in GENERIC_DRUGS or key in DRUG_ATC or key in BRAND_TO_GENERIC:
        return True
    concept = resolve_product(key)
    generic = concept.preferred_generic
    return bool(generic and (generic in GENERIC_DRUGS or generic in DRUG_ATC))


def map_drug(
    verbatim: str,
    *,
    online: bool = False,
    with_similarity: bool = True,
) -> DrugChemicalMap:
    """Resolve a drug surface to ingredient, ATC ladder, and chemical structure."""
    audit = _audit(online)
    key = _clean(verbatim)
    if not key:
        return DrugChemicalMap(verbatim=verbatim or "", matched=False,
                               match_method="empty", audit=audit)

    concept = resolve_product(key, online=online)
    generic = concept.preferred_generic or key
    atc = concept.atc
    row = crosswalk.crosswalk_row("drug", generic)
    if not atc:
        atc = row.get("atc")

    chemical = chemical_for(generic)
    if chemical is None and concept.chebi_id:
        chemical = ChemicalStructure(chebi_id=concept.chebi_id, source="ontology_curated")
    if chemical and concept.chemicals:
        chemical = chemical.model_copy(update={"iupac_style_names": list(concept.chemicals)})

    known = generic in GENERIC_DRUGS or generic in DRUG_ATC or bool(atc)
    method = "unmatched"
    if known:
        method = "brand_map" if key != generic else "generic_lexicon"
        if concept.rxcui:
            method = "rxnorm_online"

    similar: List[SimilarDrug] = []
    if with_similarity and chemical and chemical.smiles:
        cohort = atc_class_members(atc[:4]) if atc and len(atc) >= 4 else None
        similar = similar_drugs(generic, cohort) or similar_drugs(generic)

    return DrugChemicalMap(
        verbatim=verbatim,
        preferred_generic=generic if known else None,
        concept_id=concept.concept_id or None,
        brands=concept.brands,
        generics=concept.generics,
        rxnorm_id=row.get("rxnorm"),
        rxcui=concept.rxcui,
        atc_code=atc,
        atc_levels=atc_levels(atc),
        chemical=chemical,
        similar_drugs=similar,
        cui=row.get("cui"),
        matched=known,
        match_method=method,
        audit=audit,
    )
