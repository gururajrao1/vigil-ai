"""Corpus retrieval driven by MCN / geo / brand query expansion."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import RawPost, Signal
from .query_expand import expand_query


def search_corpus_with_expansion(
    db: Session,
    query: str,
    *,
    project_id: Optional[int] = None,
    limit_posts: int = 12,
    limit_signals: int = 12,
    online: bool = False,
) -> dict:
    """Expand the query, then find posts/signals matching ANY synonym term.

    This is the VigilAI realisation of Pattabhi's Chennai≡Madras / diabetes-cohort
    / Janumet→chemical examples: expansion is what makes the ontology *useful*.
    """
    expansion = expand_query(query, online=online)
    terms = [t for t in (expansion.get("search_terms") or []) if len(t) >= 2][:40]
    if not terms and (query or "").strip():
        terms = [query.strip().lower()]

    post_hits: List[dict] = []
    signal_hits: List[dict] = []

    if db is not None and terms:
        post_filters = []
        for t in terms:
            like = f"%{t}%"
            post_filters.append(RawPost.title.ilike(like))
            post_filters.append(RawPost.body.ilike(like))
            # Country/region columns for geo when the alias equals a country name
            post_filters.append(RawPost.country.ilike(like))
            post_filters.append(RawPost.region.ilike(like))

        pq = db.query(RawPost).filter(or_(*post_filters))
        if project_id is not None:
            from ..api.helpers import _project_scope

            pq = pq.filter(_project_scope(RawPost.project_id, project_id))
        for row in pq.order_by(RawPost.posted_at.desc().nullslast()).limit(limit_posts).all():
            matched = [t for t in terms if t in ((row.title or "") + " " + (row.body or "")).lower()
                       or t in (row.country or "").lower() or t in (row.region or "").lower()]
            post_hits.append({
                "id": row.id,
                "platform": row.platform,
                "country": row.country,
                "region": row.region,
                "title": (row.title or "")[:180],
                "excerpt": ((row.body or "")[:220]),
                "matched_terms": matched[:8],
                "posted_at": row.posted_at.isoformat() if row.posted_at else None,
            })

        sig_filters = []
        for t in terms:
            like = f"%{t}%"
            sig_filters.append(Signal.drug.ilike(like))
            sig_filters.append(Signal.symptom.ilike(like))
            sig_filters.append(Signal.meddra_pt.ilike(like))
        sq = db.query(Signal).filter(or_(*sig_filters))
        if project_id is not None:
            from ..api.helpers import _project_scope

            sq = sq.filter(_project_scope(Signal.project_id, project_id))
        for sig in sq.order_by(Signal.post_count.desc().nullslast()).limit(limit_signals).all():
            signal_hits.append({
                "id": sig.id,
                "drug": sig.drug,
                "event": sig.symptom,
                "meddra_pt": sig.meddra_pt,
                "strength": sig.strength,
                "post_count": sig.post_count,
                "prr": sig.prr,
                "spatial_cluster": bool(sig.spatial_cluster),
            })

    teaching = {
        "headline": "Ontology is for retrieval + counting — not a static dictionary UI",
        "geo": (
            "If you search Chennai, Madras-tagged narratives must appear. "
            "Aliases expand the search bag; they are not a city picker."
        ),
        "clinical": (
            "diabetic + Type 2 diabetic mellitus + diabetes → one CUI / MedDRA PT; "
            "sum patient counts (N) before PRR/ROR so frequency tables do not fragment."
        ),
        "brand": (
            "Janumet → sitagliptin + metformin (chemical universe); peer brands are "
            "subsets you can compare on the same population."
        ),
    }

    return {
        "query": query,
        "expansion": expansion,
        "post_hits": post_hits,
        "signal_hits": signal_hits,
        "n_posts": len(post_hits),
        "n_signals": len(signal_hits),
        "teaching": teaching,
    }
