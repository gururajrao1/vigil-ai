"""One-shot cleanup of junk labels in Signal rows and ProcessedPost.entities_json.

Applies the same canonicalizers used at ingest: products, events, conditions.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost, Signal
from ..nlp.condition_norm import canonical_condition
from ..nlp.drug_norm import canonical_product
from ..nlp.meddra import map_term
from ..nlp.text_normalize import canonical_event, fold_key

logger = logging.getLogger("vigilai.normalize_cleanup")


def scrub_entities_json(db: Session, project_id: Optional[int] = None) -> dict:
    """Rewrite drugs / symptoms / conditions inside entities_json."""
    q = db.query(ProcessedPost)
    if project_id is not None:
        q = (
            q.join(RawPost, ProcessedPost.raw_id == RawPost.id)
            .filter(RawPost.project_id == project_id)
        )

    updated_posts = 0
    stats = {
        "symptoms_rewritten": 0, "symptoms_dropped": 0,
        "conditions_rewritten": 0, "conditions_dropped": 0,
        "drugs_rewritten": 0, "drugs_dropped": 0,
    }

    for proc in q.all():
        try:
            ent = json.loads(proc.entities_json or "{}")
        except json.JSONDecodeError:
            continue
        changed = False

        # Symptoms / AEs
        new_symptoms, seen_s = [], set()
        for s in ent.get("symptoms", []):
            surface = s.get("pt") or s.get("normalized") or s.get("text") or ""
            ev = canonical_event(surface)
            if not ev:
                stats["symptoms_dropped"] += 1
                changed = True
                continue
            term = map_term(ev.lower())
            pt = term.get("pt") or ev
            key = fold_key(pt)
            if key in seen_s:
                changed = True
                continue
            seen_s.add(key)
            row = dict(s)
            if row.get("pt") != pt or row.get("normalized") != pt.lower():
                stats["symptoms_rewritten"] += 1
                changed = True
            row["pt"] = pt
            row["normalized"] = pt.lower()
            if term.get("soc"):
                row["soc"] = term["soc"]
            if term.get("soc_code"):
                row["soc_code"] = term["soc_code"]
            new_symptoms.append(row)

        # Conditions / indications
        new_conds, seen_c = [], set()
        for c in ent.get("conditions", []):
            surface = c.get("normalized") or c.get("text") or ""
            canon = canonical_condition(surface)
            if not canon:
                stats["conditions_dropped"] += 1
                changed = True
                continue
            key = fold_key(canon)
            if key in seen_c:
                changed = True
                continue
            seen_c.add(key)
            row = dict(c)
            if row.get("normalized") != canon:
                stats["conditions_rewritten"] += 1
                changed = True
            row["normalized"] = canon
            new_conds.append(row)

        # Drugs / products
        new_drugs, seen_d = [], set()
        for d in ent.get("drugs", []):
            surface = d.get("normalized") or d.get("text") or ""
            canon = canonical_product(surface)
            if not canon:
                stats["drugs_dropped"] += 1
                changed = True
                continue
            key = fold_key(canon)
            if key in seen_d:
                changed = True
                continue
            seen_d.add(key)
            row = dict(d)
            if row.get("normalized") != canon:
                stats["drugs_rewritten"] += 1
                changed = True
            row["normalized"] = canon
            row["generic"] = canon
            new_drugs.append(row)

        if changed:
            ent["symptoms"] = new_symptoms
            ent["conditions"] = new_conds
            ent["drugs"] = new_drugs
            proc.entities_json = json.dumps(ent)
            updated_posts += 1

    db.commit()
    logger.info("scrub_entities_json posts=%s stats=%s", updated_posts, stats)
    return {"posts_updated": updated_posts, **stats}


def scrub_signal_labels(db: Session, project_id: Optional[int] = None) -> dict:
    """Rewrite Signal labels; scrub entities; merge duplicate (drug, event) rows."""
    entity_scrub = scrub_entities_json(db, project_id=project_id)

    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)

    rows = q.all()
    deleted = 0
    updated = 0
    best: dict[str, Signal] = {}
    doomed: list[Signal] = []

    for s in rows:
        drug = canonical_product(s.drug or "") or (s.drug or "").strip().lower()
        ev = canonical_event(s.meddra_pt or s.symptom or "")
        if not drug or not ev:
            doomed.append(s)
            continue
        term = map_term(ev.lower())
        pt = term.get("pt") or ev
        s.drug = drug
        s.symptom = pt.lower()
        s.meddra_pt = pt
        if term.get("soc"):
            s.meddra_soc = term["soc"]
        if term.get("soc_code"):
            s.meddra_soc_code = term["soc_code"]
        updated += 1
        key = f"{fold_key(drug)}|{fold_key(pt)}"
        prev = best.get(key)
        if prev is None:
            best[key] = s
        else:
            if float(s.prr or 0) >= float(prev.prr or 0):
                doomed.append(prev)
                best[key] = s
            else:
                doomed.append(s)

    for s in doomed:
        db.delete(s)
        deleted += 1

    db.commit()
    logger.info("scrub_signal_labels updated=%s deleted=%s", updated, deleted)
    return {
        "updated": updated,
        "deleted": deleted,
        "remaining": len(best),
        "entities": entity_scrub,
    }
