"""Database schema packages (OMOP CDM staging and related).

Eager imports are avoided so ``app.database`` can load ``app.db.pg_url``
without a circular import through ``omop_models`` → ``Base``.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "Concept",
    "ConditionOccurrence",
    "DrugExposure",
    "Person",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import omop_models

        return getattr(omop_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
