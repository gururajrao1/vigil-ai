"""Expand-then-pool comparison across a product's naming tiers.

Answers the question a safety reviewer actually asks: "if I search the brand,
the generic, and the chemical name separately, do I see the same safety picture?"

Counts AE-flagged posts per observed alias and pooled under one product concept,
so fragmentation across brand / INN dual / chemical naming is visible instead of
silently splitting a signal.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost
from ..nlp.ontology import ontology_stack, resolve_product

_DISCLAIMER = (
    "Alias pooling uses curated brand/INN/chemical crosswalks plus optional "
    "keyless RxNorm and ChEBI lookups. Open surrogates — not licensed MedDRA, "
    "SNOMED-CT, or UMLS. Open terminology crosswalk output."
)


def _post_drug_surfaces(entities_json: Optional[str]) -> List[Dict[str, str]]:
    try:
        ents = json.loads(entities_json or "{}") or {}
    except Exception:
        return []
    out = []
    for drug in ents.get("drugs") or []:
        out.append({
            "surface": (drug.get("text") or "").strip().lower(),
            "normalized": (drug.get("normalized") or drug.get("generic") or "").strip().lower(),
            "concept_id": drug.get("concept_id") or "",
        })
    return out


def compare_product_aliases(
    db: Session,
    term: str,
    *,
    project_id: Optional[int] = None,
    online: bool = False,
) -> dict:
    """Per-alias vs pooled AE counts for one product concept."""
    concept = resolve_product(term, online=online)
    if not concept.preferred_generic:
        return {
            "term": term,
            "concept": None,
            "pooled": {"n_ae_posts": 0, "n_aliases_seen": 0},
            "by_alias": [],
            "verdict": "Provide a product name to expand.",
            "ontology_stack": ontology_stack(),
            "disclaimer": _DISCLAIMER,
        }

    alias_set = {a for a in concept.aliases() if a}
    tier_of: Dict[str, str] = {}
    for name in concept.chemicals:
        tier_of[name] = "chemical"
    for name in concept.brands:
        tier_of[name] = "brand"
    for name in [concept.preferred_generic, *concept.generics]:
        tier_of[name] = "generic"

    q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
    )
    if project_id is not None:
        q = q.filter(RawPost.project_id == project_id)

    per_alias: Counter = Counter()
    platforms_by_alias: Dict[str, Counter] = defaultdict(Counter)
    pooled_post_ids: set[int] = set()
    pooled_platforms: Counter = Counter()

    for processed, raw in q.all():
        matched_aliases = set()
        for drug in _post_drug_surfaces(processed.entities_json):
            if drug["concept_id"] and drug["concept_id"] == concept.concept_id:
                matched_aliases.add(drug["surface"] or drug["normalized"])
                continue
            for candidate in (drug["surface"], drug["normalized"]):
                if candidate and candidate in alias_set:
                    matched_aliases.add(candidate)
        if not matched_aliases:
            continue
        pooled_post_ids.add(processed.id)
        pooled_platforms[raw.platform or "unknown"] += 1
        for alias in matched_aliases:
            per_alias[alias] += 1
            platforms_by_alias[alias][raw.platform or "unknown"] += 1

    by_alias = [
        {
            "alias": alias,
            "tier": tier_of.get(alias, "observed"),
            "n_ae_posts": count,
            "share_of_pooled": round(count / len(pooled_post_ids), 3) if pooled_post_ids else 0.0,
            "platforms": [p for p, _ in platforms_by_alias[alias].most_common(4)],
        }
        for alias, count in per_alias.most_common()
    ]

    n_pooled = len(pooled_post_ids)
    top = by_alias[0] if by_alias else None
    if not n_pooled:
        verdict = (
            f"No AE-flagged posts mention {concept.preferred_generic} under any of its "
            f"{len(alias_set)} known aliases in this workspace."
        )
    elif top and top["n_ae_posts"] < n_pooled:
        verdict = (
            f"Pooling {len(by_alias)} observed aliases raises the AE base from "
            f"{top['n_ae_posts']} (best single name: {top['alias']}) to {n_pooled} posts — "
            "searching one name alone would under-count this product."
        )
    else:
        verdict = (
            f"{n_pooled} AE posts all surface under \"{top['alias']}\"; no naming "
            "fragmentation detected for this concept in the current corpus."
        )

    return {
        "term": term,
        "concept": concept.to_dict(),
        "pooled": {
            "n_ae_posts": n_pooled,
            "n_aliases_seen": len(by_alias),
            "n_aliases_known": len(alias_set),
            "platforms": [p for p, _ in pooled_platforms.most_common(6)],
        },
        "by_alias": by_alias,
        "verdict": verdict,
        "how_to_use": (
            "Compare per-alias counts with the pooled total. A large gap means the "
            "safety picture is split across brand / generic / chemical naming and "
            "should be reviewed as one concept."
        ),
        "ontology_stack": ontology_stack(),
        "disclaimer": _DISCLAIMER,
    }
