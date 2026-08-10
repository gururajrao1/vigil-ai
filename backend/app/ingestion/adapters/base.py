"""Shared adapter interface — fetch → privacy hygiene → ready for pipeline."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ...privacy.hygiene import HygieneResult, apply_hygiene_to_ingest_dict


@dataclass
class AdapterResult:
    source: str
    posts: List[Dict[str, Any]] = field(default_factory=list)
    suppressed_duplicates: int = 0
    skipped_empty: int = 0
    hygiene: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "n_posts": len(self.posts),
            "suppressed_duplicates": self.suppressed_duplicates,
            "skipped_empty": self.skipped_empty,
            "posts": self.posts,
            "meta": self.meta,
        }


class IngestAdapter(ABC):
    """One modular connector for a heterogeneous data stream."""

    name: str = "base"

    @abstractmethod
    def fetch(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Return raw ingest dicts (title/body/author/platform/…)."""

    def run(
        self,
        *,
        db: Optional[Session] = None,
        project_id: Optional[int] = None,
        apply_hygiene: bool = True,
        **kwargs: Any,
    ) -> AdapterResult:
        raw_posts = self.fetch(**kwargs)
        out = AdapterResult(source=self.name, meta={"fetched": len(raw_posts)})
        if not apply_hygiene:
            out.posts = raw_posts
            return out
        for rec in raw_posts:
            cleaned, hyg = apply_hygiene_to_ingest_dict(
                rec, db=db, project_id=project_id
            )
            out.hygiene.append(hyg.to_dict())
            if hyg.action == "suppress_duplicate":
                out.suppressed_duplicates += 1
                continue
            if hyg.action == "skip_empty":
                out.skipped_empty += 1
                continue
            out.posts.append(cleaned)
        return out
