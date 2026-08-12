"""Step 3 — Hierarchical cohort aggregation of synonymous clinical mentions.

Maps fragmented variants (e.g. diabetic / Type 2 diabetic mellitus / diabetes)
onto a single UMLS CUI with dual MedDRA + SNOMED codes, then sums discrete
patient counts into one demographic cohort N for disproportionality math.
"""
from __future__ import annotations

from typing import List, Sequence, Union

from .models import AggregatedCohort, CohortAggregationResult, MentionInput
from .umls_linker import link_to_umls


def _as_mentions(
    mentions: Sequence[Union[MentionInput, dict, tuple, str]],
) -> List[MentionInput]:
    out: List[MentionInput] = []
    for item in mentions:
        if isinstance(item, MentionInput):
            out.append(item)
        elif isinstance(item, str):
            out.append(MentionInput(verbatim=item, patient_count=1))
        elif isinstance(item, dict):
            out.append(MentionInput(**item))
        elif isinstance(item, (tuple, list)) and len(item) >= 1:
            count = int(item[1]) if len(item) > 1 else 1
            out.append(MentionInput(verbatim=str(item[0]), patient_count=count))
        else:
            raise TypeError(f"Unsupported mention payload: {type(item)!r}")
    return out


def aggregate_clinical_cohorts(
    mentions: Sequence[Union[MentionInput, dict, tuple, str]],
) -> CohortAggregationResult:
    """Collapse synonym fragments onto one CUI and sum patient counts."""
    inputs = _as_mentions(mentions)
    buckets: dict[str, AggregatedCohort] = {}
    unresolved: List[str] = []

    for mention in inputs:
        link = link_to_umls(mention.verbatim)
        if not link.matched or not link.cui:
            unresolved.append(mention.verbatim)
            continue
        bucket = buckets.get(link.cui)
        if bucket is None:
            bucket = AggregatedCohort(
                cui=link.cui,
                preferred=link.preferred or link.meddra_pt or link.cui,
                meddra_pt=link.meddra_pt,
                snomed_ct=link.snomed_ct,
                variants=[],
                patient_count=0,
                mention_count=0,
            )
            buckets[link.cui] = bucket
        if mention.verbatim not in bucket.variants:
            bucket.variants.append(mention.verbatim)
        bucket.patient_count += int(mention.patient_count or 0)
        bucket.mention_count += 1

    cohorts = sorted(buckets.values(), key=lambda c: (-c.patient_count, c.preferred))
    return CohortAggregationResult(
        inputs=inputs,
        cohorts=cohorts,
        total_patients=sum(c.patient_count for c in cohorts),
        unresolved=unresolved,
    )


def diabetes_demo_cohort() -> CohortAggregationResult:
    """Canonical demo: diabetic(2) + Type 2 diabetic mellitus(3) + diabetes(5) → N=10."""
    return aggregate_clinical_cohorts(
        [
            MentionInput(verbatim="diabetic", patient_count=2),
            MentionInput(verbatim="Type 2 diabetic mellitus", patient_count=3),
            MentionInput(verbatim="diabetes", patient_count=5),
        ]
    )
