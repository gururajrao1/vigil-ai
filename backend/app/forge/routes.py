"""Forge API: generate synthetic patient posts, list, and export (JSONL/CSV)."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_role
from ..database import get_db
from ..models import ForgeRecord
from .engine import generate_batch

router = APIRouter(prefix="/api/forge", tags=["forge"])


class ForgeRequest(BaseModel):
    drug: str
    condition: str
    platform: str = "reddit"
    region: str = "Global"
    language: str = "English"
    symptom: str | None = None
    records: int = 5


@router.post("/generate")
def forge_generate(req: ForgeRequest, db: Session = Depends(get_db),
                   _user=Depends(require_role("analyst"))):
    result = generate_batch(
        drug=req.drug, condition=req.condition, platform=req.platform,
        region=req.region, language=req.language, symptom=req.symptom,
        records=req.records,
    )
    for r in result["records"]:
        db.add(ForgeRecord(
            batch_id=r["batch_id"], drug=r["drug"], condition=r["condition"],
            platform=r["platform"], region=r["region"], language=r["language"],
            post_text=r["post_text"], structured_json=json.dumps(r["structured"]),
            scenario_json=json.dumps(r["scenario"]), quality_score=r["quality_score"],
            scores_json=json.dumps(r["scores"]), export_ready=r["export_ready"],
            repaired=r["repaired"], source=r["source"],
        ))
    db.commit()
    return result


@router.get("/records")
def forge_records(batch_id: str | None = None, limit: int = 50,
                  db: Session = Depends(get_db)):
    q = db.query(ForgeRecord)
    if batch_id:
        q = q.filter(ForgeRecord.batch_id == batch_id)
    rows = q.order_by(ForgeRecord.created_at.desc()).limit(limit).all()
    return {"records": [_row(r) for r in rows]}


@router.get("/export/jsonl")
def export_jsonl(batch_id: str | None = None, ready_only: bool = True,
                 db: Session = Depends(get_db)):
    rows = _export_rows(db, batch_id, ready_only)
    buf = io.StringIO()
    for r in rows:
        buf.write(json.dumps(_row(r)) + "\n")
    return Response(content=buf.getvalue(), media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=forge_export.jsonl"})


@router.get("/export/csv")
def export_csv(batch_id: str | None = None, ready_only: bool = True,
               db: Session = Depends(get_db)):
    rows = _export_rows(db, batch_id, ready_only)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "drug", "condition", "platform", "region", "language",
                "quality_score", "export_ready", "post_text"])
    for r in rows:
        w.writerow([r.id, r.drug, r.condition, r.platform, r.region, r.language,
                    r.quality_score, r.export_ready, r.post_text])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=forge_export.csv"})


def _export_rows(db, batch_id, ready_only):
    q = db.query(ForgeRecord)
    if batch_id:
        q = q.filter(ForgeRecord.batch_id == batch_id)
    if ready_only:
        q = q.filter(ForgeRecord.export_ready.is_(True))
    return q.order_by(ForgeRecord.created_at.desc()).all()


def _row(r: ForgeRecord) -> dict:
    return {
        "id": r.id, "batch_id": r.batch_id, "drug": r.drug, "condition": r.condition,
        "platform": r.platform, "region": r.region, "language": r.language,
        "post_text": r.post_text,
        "structured": json.loads(r.structured_json or "{}"),
        "scenario": json.loads(r.scenario_json or "{}"),
        "scores": json.loads(r.scores_json or "{}"),
        "quality_score": r.quality_score, "export_ready": r.export_ready,
        "repaired": r.repaired, "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
