"""Shared AE corpus extraction for masking, DDI, pregnancy, and remine paths.

Rebuilds (product, event) report pairs from ProcessedPost/RawPost the same way
``pipeline.recompute_signals`` does, without writing signals. Offline / deterministic.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost
from ..nlp.devices import is_known_device
from ..nlp.drug_norm import canonical_product
from ..nlp.text_normalize import canonical_event


def iter_ae_rows(db: Session, project_id: Optional[int] = None):
    """Yield (ProcessedPost, RawPost) for AE-flagged posts in scope."""
    q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
    )
    if project_id is not None:
        q = q.filter(RawPost.project_id == project_id)
    return q.all()


def extract_post_products_events(
    processed: ProcessedPost, raw: RawPost
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Return (product_list, event_list, meta) for one AE post."""
    entities = json.loads(processed.entities_json or "{}")
    negation = json.loads(processed.negation_json or "{}")
    ptype_raw = getattr(raw, "product_type", None) or "drug"

    drugs: List[str] = []
    seen_d: set[str] = set()
    for d in entities.get("drugs", []):
        canon = canonical_product(d.get("normalized") or d.get("text") or "")
        if not canon or canon in seen_d:
            continue
        is_dev = (
            bool(d.get("is_device"))
            or d.get("product_type") == "device"
            or is_known_device(canon)
        )
        if ptype_raw == "device" and is_known_device(canon):
            is_dev = True
        # Skip pure devices for DDI; keep for masking reports
        seen_d.add(canon)
        drugs.append(canon)

    events: List[str] = []
    seen_e: set[str] = set()
    for s in entities.get("symptoms", []):
        if negation.get(s.get("normalized"), False):
            continue
        ev = canonical_event(s.get("pt") or s.get("normalized") or s.get("text") or "")
        if not ev or ev in seen_e:
            continue
        seen_e.add(ev)
        events.append(ev)

    text = f"{raw.title or ''} {raw.body or ''}".strip()
    meta = {
        "post_id": processed.id,
        "text": text,
        "posted_at": raw.posted_at,
        "country": raw.country,
        "region": raw.region or "Global",
        "source": raw.platform,
        "content_type": "icsr" if (raw.platform or "").startswith(("vaers", "faers")) else "social",
    }
    return drugs, events, meta


def build_ae_reports(
    db: Session, project_id: Optional[int] = None
) -> Dict[str, Any]:
    """Build report pairs + per-post multi-drug bags for analytics overlays.

    Returns
    -------
    dict with keys:
      reports: List[(drug, event)]  — one entry per co-occurrence (DMA input)
      posts: List[{drugs, events, meta}]  — bag-level for DDI / pregnancy
    """
    reports: List[Tuple[str, str]] = []
    posts: List[dict] = []

    for processed, raw in iter_ae_rows(db, project_id):
        drugs, events, meta = extract_post_products_events(processed, raw)
        if not drugs or not events:
            continue
        posts.append({"drugs": drugs, "events": events, **meta})
        for drug in drugs:
            for event in events:
                reports.append((drug, event))

    return {"reports": reports, "posts": posts}


def filter_reports_excluding_drugs(
    reports: List[Tuple[str, str]], exclude: set[str]
) -> List[Tuple[str, str]]:
    """Drop any (drug, event) where drug is in the exclude set (unmask remine)."""
    if not exclude:
        return list(reports)
    excl = {e.lower() for e in exclude}
    return [(d, e) for d, e in reports if d.lower() not in excl]


def reports_from_posts_excluding_maskers(
    posts: List[dict], exclude_drugs: set[str]
) -> List[Tuple[str, str]]:
    """Rebuild DMA pairs after removing entire posts that mention a masker drug.

    Classic competition-bias unmasking: drop reports that co-occur with the
    dominant masker so the residual corpus can reveal suppressed signals.
    """
    excl = {e.lower() for e in exclude_drugs}
    out: List[Tuple[str, str]] = []
    for p in posts:
        drugs = [d for d in p["drugs"] if d.lower() not in excl]
        if not drugs:
            continue
        # If any masker was present on the original post, drop the whole post
        # (standard leave-one-drug-out / competition-bias approach).
        if any(d.lower() in excl for d in p["drugs"]):
            continue
        for drug in drugs:
            for event in p["events"]:
                out.append((drug, event))
    return out
