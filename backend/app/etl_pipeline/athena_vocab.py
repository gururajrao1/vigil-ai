"""Athena vocabulary surrogate sync — re-seed OMOP CONCEPT from RxE + MCN.

Licensed OHDSI Athena dumps are not redistributed. This path upserts the
offline RxNorm Extension / MedDRA-style surrogates into ``omop_concept``
after BIGINT-safe concept_id hashing.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..db.omop_concept_seed import seed_concepts_from_surrogates


def sync_athena_vocab_surrogates(db: Session) -> dict:
    """Upsert CONCEPT rows from bundled RxE + MCN catalogs."""
    seeded = seed_concepts_from_surrogates(db)
    return {
        "mode": "surrogate_rxe_mcn",
        "vocabulary": "RxNorm Extension / MedDRA / SNOMED gender (surrogate)",
        **seeded,
    }
