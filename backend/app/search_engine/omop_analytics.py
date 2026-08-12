"""Step 5 — Universe vs Subset disproportionality over OMOP-shaped exposures.

Universe (denominator): AE reports pooled under the *generic ingredient* chemical
makeup (all manufacturers / brands that share Has_Ingredient).

Subset (comparators): AE reports tagged to specific branded surfaces, for
head-to-head contrast against the generic baseline (e.g. branded formulation vs
chemical class).

Uses VigilAI Signal + ProcessedPost evidence when OMOP staging is thin, and
OMOP DRUG_EXPOSURE × CONDITION_OCCURRENCE joins when populated — same math via
``compute_signals``.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from ..analytics.disproportionality import compute_signals
from ..models import Signal
from ..nlp.ontology import aliases_for_product, resolve_product
from .models import (
    AuditStamp,
    BrandChemicalResolution,
    UniverseSubsetReport,
    UniverseSubsetRow,
)
from .rxnorm_mapper import subset_brands_for_ingredients

_HOW_TO_READ = (
    "Universe rows pool every brand/formulation that shares the resolved "
    "ingredient(s) — the chemical baseline. Subset rows restrict to the selected "
    "brand surface(s). Comparative PRR elevation (subset vs universe) highlights "
    "formulation- or manufacturer-specific disproportion against the generic class."
)


def _alias_set(terms: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for term in terms:
        t = (term or "").strip().lower()
        if not t:
            continue
        out.add(t)
        out |= {a.lower() for a in aliases_for_product(t)}
        concept = resolve_product(t)
        if concept.preferred_generic:
            out.add(concept.preferred_generic.lower())
            out.update(b.lower() for b in concept.brands)
    return {a for a in out if a}


def _pairs_from_signals(
    db: Session,
    products: Set[str],
    *,
    project_id: Optional[int] = None,
) -> List[Tuple[str, str]]:
    if not products:
        return []
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    pairs: List[Tuple[str, str]] = []
    for sig in q.all():
        drug = (sig.drug or "").strip().lower()
        if drug not in products:
            continue
        event = (sig.meddra_pt or sig.symptom or "").strip()
        if not event:
            continue
        count = max(1, int(sig.post_count or 1))
        pairs.extend([(drug, event)] * count)
    return pairs


def _pairs_from_omop(
    db: Session,
    concept_keys: Set[str],
    *,
    project_id: Optional[int] = None,
) -> List[Tuple[str, str]]:
    """Join OMOP drug_exposure → condition_occurrence on person_id."""
    try:
        from ..db.schemas.omop_cdm import (  # noqa: PLC0415
            CONDITION_TYPE_PRIMARY_AE,
            OmopConditionOccurrence,
            OmopDrugExposure,
        )
    except Exception:
        return []

    if not concept_keys:
        return []

    dq = db.query(OmopDrugExposure)
    if project_id is not None:
        dq = dq.filter(OmopDrugExposure.project_id == project_id)
    exposures = []
    for row in dq.all():
        concept = (row.drug_concept_id or "").strip().lower()
        source = (row.drug_source_value or "").strip().lower()
        if concept in concept_keys or source in concept_keys:
            exposures.append(row)
        else:
            # ATC prefix / preferred generic substring match
            if any(k and (k in concept or k in source) for k in concept_keys):
                exposures.append(row)
    if not exposures:
        return []

    person_ids = {e.person_id for e in exposures}
    cq = db.query(OmopConditionOccurrence).filter(
        OmopConditionOccurrence.person_id.in_(person_ids),
        OmopConditionOccurrence.condition_type_concept_id == CONDITION_TYPE_PRIMARY_AE,
    )
    if project_id is not None:
        cq = cq.filter(OmopConditionOccurrence.project_id == project_id)
    conditions_by_person: Dict[int, List[str]] = {}
    for cond in cq.all():
        pt = (cond.condition_concept_id or cond.condition_source_value or "").strip()
        if pt:
            conditions_by_person.setdefault(cond.person_id, []).append(pt)

    pairs: List[Tuple[str, str]] = []
    for exp in exposures:
        label = (exp.drug_source_value or exp.drug_concept_id or "drug").strip().lower()
        for pt in conditions_by_person.get(exp.person_id, []):
            pairs.append((label, pt))
    return pairs


def _to_rows(stats: List[dict], scope: str) -> List[UniverseSubsetRow]:
    return [
        UniverseSubsetRow(
            product=s["drug"],
            event=s["symptom"],
            scope=scope,  # type: ignore[arg-type]
            post_count=int(s.get("post_count") or 0),
            prr=s.get("prr"),
            ror=s.get("ror"),
            chi_square=s.get("chi_square"),
            eb05=s.get("eb05"),
            ic025=s.get("ic025"),
            strength=s.get("strength"),
            sdr_flag=bool(s.get("sdr_flag")),
        )
        for s in stats
    ]


def _compare(universe: List[UniverseSubsetRow], subset: List[UniverseSubsetRow]) -> List[dict]:
    u_by_event = {r.event.lower(): r for r in universe}
    out = []
    for s in subset:
        u = u_by_event.get(s.event.lower())
        if not u or not u.prr or not s.prr:
            continue
        ratio = round(s.prr / u.prr, 3) if u.prr else None
        out.append({
            "event": s.event,
            "subset_product": s.product,
            "subset_prr": s.prr,
            "universe_prr": u.prr,
            "prr_elevation": ratio,
            "subset_eb05": s.eb05,
            "universe_eb05": u.eb05,
            "subset_sdr": s.sdr_flag,
            "universe_sdr": u.sdr_flag,
            "note": (
                "Subset PRR elevated vs chemical universe"
                if ratio and ratio >= 1.5 else
                "Subset similar to chemical universe baseline"
            ),
        })
    out.sort(key=lambda r: (r.get("prr_elevation") or 0), reverse=True)
    return out


def compute_universe_vs_subset(
    db: Session,
    resolution: BrandChemicalResolution,
    *,
    subset_brands: Optional[Sequence[str]] = None,
    project_id: Optional[int] = None,
    top_n: int = 40,
) -> UniverseSubsetReport:
    """Run Universe (ingredient) vs Subset (brand) disproportionality."""
    audit = AuditStamp(
        source="omop_universe_subset",
        dictionaries=["omop_cdm", "signals", "rxe_extension_surrogate.json"],
    )
    generics = [i.generic for i in resolution.ingredients]
    if not generics:
        return UniverseSubsetReport(
            query_term=resolution.query_term,
            verdict="No resolved ingredients — cannot build a chemical universe.",
            how_to_read=_HOW_TO_READ,
            audit=audit,
        )

    universe_aliases = _alias_set(generics)
    # include all known brand surfaces for these ingredients in the universe pool
    auto_brands = subset_brands_for_ingredients(generics)
    universe_aliases |= _alias_set(auto_brands)

    selected = list(subset_brands) if subset_brands is not None else (
        [resolution.brand_name] if resolution.brand_name else auto_brands[:3]
    )
    selected = [s.strip().lower() for s in selected if s and s.strip()]
    subset_aliases = _alias_set(selected) if selected else set()

    # Prefer OMOP pairs; fall back to Signal table
    omop_u = _pairs_from_omop(db, universe_aliases, project_id=project_id)
    omop_s = _pairs_from_omop(db, subset_aliases, project_id=project_id) if subset_aliases else []

    universe_pairs = omop_u or _pairs_from_signals(db, universe_aliases, project_id=project_id)
    subset_pairs = omop_s or (
        _pairs_from_signals(db, subset_aliases, project_id=project_id) if subset_aliases else []
    )

    # For universe, re-key products to preferred generic so brands pool
    generic_key = generics[0] if len(generics) == 1 else "+".join(sorted(generics))
    universe_keyed = [(generic_key, event) for _, event in universe_pairs]

    u_stats = compute_signals(universe_keyed)[:top_n] if universe_keyed else []
    s_stats = compute_signals(subset_pairs)[:top_n] if subset_pairs else []
    u_rows = _to_rows(u_stats, "universe")
    s_rows = _to_rows(s_stats, "subset")
    comparative = _compare(u_rows, s_rows)

    if not universe_keyed:
        verdict = (
            "No AE-coded exposures for this chemical universe in the active workspace. "
            "Ingest data / sync OMOP, then retry."
        )
    elif not subset_pairs:
        verdict = (
            f"Universe has {len(universe_keyed)} report-rows for {generic_key}; "
            "no subset brand reports selected — pick a manufacturer brand to compare."
        )
    elif comparative and (comparative[0].get("prr_elevation") or 0) >= 1.5:
        top = comparative[0]
        verdict = (
            f"Subset «{top['subset_product']}» shows PRR elevation "
            f"{top['prr_elevation']}× vs chemical universe for {top['event']}."
        )
    else:
        verdict = (
            f"Subset brands look similar to the {generic_key} chemical universe — "
            "no strong formulation-specific disproportion in this scope."
        )

    return UniverseSubsetReport(
        query_term=resolution.query_term,
        universe_ingredients=generics,
        subset_brands=selected,
        universe_rows=u_rows,
        subset_rows=s_rows,
        comparative=comparative,
        totals={
            "universe_reports": len(universe_keyed),
            "subset_reports": len(subset_pairs),
            "universe_events": len(u_rows),
            "subset_events": len(s_rows),
            "omop_universe_pairs": len(omop_u),
            "omop_subset_pairs": len(omop_s),
        },
        verdict=verdict,
        how_to_read=_HOW_TO_READ,
        audit=audit,
    )
