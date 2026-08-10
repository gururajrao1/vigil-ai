"""PBRER / PSUR draft generator — ICH E2C (R2) sections 16–17 shape.

AI-assisted draft requiring QPPV / Medical Reviewer validation. Not a submission.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from ..models import Signal

_DISCLAIMER = (
    "AI-ASSISTED DRAFT — Periodic Benefit-Risk Evaluation Report (PBRER/PSUR) "
    "sections shaped after ICH E2C (R2). Requires QPPV / Medical Reviewer "
    "validation. Synthetic/social data may be fictional; openFDA = US only; "
    "MedDRA is an open surrogate. NOT a validated regulatory submission; "
    "NOT for clinical use."
)


def build_pbrer_payload(
    db: Session,
    *,
    signal_id: Optional[int] = None,
    project_id: Optional[int] = None,
    limit: int = 40,
) -> dict:
    """Aggregate open signals into PBRER-shaped sections 16 and 17."""
    q = db.query(Signal)
    if signal_id is not None:
        q = q.filter(Signal.id == signal_id)
    if project_id is not None:
        from sqlalchemy import or_

        q = q.filter(
            or_(Signal.project_id == project_id, Signal.project_id.is_(None), Signal.project_id == 0)
        )
    # Prefer open lifecycle signals for periodic evaluation
    rows: List[Signal] = (
        q.order_by(Signal.priority_score.desc())
        .limit(limit)
        .all()
    )
    rows = sorted(rows, key=lambda s: s.priority_score or 0.0, reverse=True)[:limit]

    signals_out = []
    for s in rows:
        status = (s.lifecycle_status or "new").lower()
        if status in ("closed", "rejected") and signal_id is None:
            continue
        signals_out.append({
            "signal_id": s.id,
            "product": s.drug,
            "event": s.meddra_pt or s.symptom,
            "strength": s.strength,
            "prr": s.prr,
            "ror": s.ror,
            "chi_square": s.chi_square,
            "who_umc": s.who_umc,
            "severity": s.severity,
            "label_novelty": s.label_novelty,
            "lifecycle_status": status,
            "priority_score": s.priority_score,
            "sdr_flag": bool(s.sdr_flag),
        })

    # Section 16 — Signal and Risk Evaluation (summary table)
    section_16 = {
        "title": "Section 16 — Signal and Risk Evaluation",
        "summary": (
            f"{len(signals_out)} open or focus signal(s) evaluated in this draft period. "
            "Disproportionality and WHO-UMC causality are social/ICSR surrogates."
        ),
        "signals": signals_out,
    }

    # Section 17 — Integrated Benefit-Risk
    strong = [x for x in signals_out if (x.get("strength") or "").upper() == "STRONG"]
    novel = [x for x in signals_out if (x.get("label_novelty") or "") == "novel"]
    section_17 = {
        "title": "Section 17 — Integrated Benefit-Risk Evaluation",
        "benefit_context": (
            "Benefit characterisation is out of scope for this social-listening prototype; "
            "retain approved indication benefit statements from the local SmPC/USPI."
        ),
        "risk_summary": (
            f"{len(strong)} STRONG SDR(s); {len(novel)} labeling-gap (novel) signal(s). "
            "Integrate with company core safety information before any labeling action."
        ),
        "conclusion_draft": (
            "Draft conclusion: continue routine pharmacovigilance; escalate CRITICAL_URGENT "
            "triangulated signals to medical review. This paragraph is machine-generated."
        ),
    }

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "document_type": "PBRER_PSUR_DRAFT",
        "ich_reference": "ICH E2C (R2)",
        "signal_id": signal_id,
        "n_signals": len(signals_out),
        "section_16": section_16,
        "section_17": section_17,
        "disclaimer": _DISCLAIMER,
    }


def render_pbrer_markdown(payload: dict) -> str:
    s16 = payload.get("section_16") or {}
    s17 = payload.get("section_17") or {}
    lines = [
        f"# PBRER / PSUR Draft — {payload.get('ich_reference')}",
        "",
        f"**Generated:** {payload.get('generated_at')}",
        f"**Signals in scope:** {payload.get('n_signals')}",
        "",
        "> " + (payload.get("disclaimer") or _DISCLAIMER),
        "",
        f"## {s16.get('title')}",
        s16.get("summary") or "",
        "",
        "| ID | Product | Event | Strength | PRR | WHO-UMC | Novelty | Lifecycle |",
        "|----|---------|-------|----------|-----|---------|---------|-----------|",
    ]
    for s in s16.get("signals") or []:
        lines.append(
            f"| {s.get('signal_id')} | {s.get('product')} | {s.get('event')} | "
            f"{s.get('strength')} | {s.get('prr')} | {s.get('who_umc')} | "
            f"{s.get('label_novelty')} | {s.get('lifecycle_status')} |"
        )
    lines += [
        "",
        f"## {s17.get('title')}",
        "",
        "### Benefit context",
        s17.get("benefit_context") or "",
        "",
        "### Risk summary",
        s17.get("risk_summary") or "",
        "",
        "### Draft conclusion",
        s17.get("conclusion_draft") or "",
        "",
    ]
    return "\n".join(lines)


def render_pbrer_pdf(payload: dict) -> bytes:
    """ReportLab PDF; falls back to UTF-8 markdown bytes if ReportLab missing."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return render_pbrer_markdown(payload).encode("utf-8")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("PBRER / PSUR Draft (ICH E2C R2)", styles["Title"]),
        Spacer(1, 8),
        Paragraph(payload.get("disclaimer") or _DISCLAIMER, styles["Normal"]),
        Spacer(1, 12),
    ]
    s16 = payload.get("section_16") or {}
    story.append(Paragraph(s16.get("title") or "Section 16", styles["Heading2"]))
    story.append(Paragraph(s16.get("summary") or "", styles["Normal"]))
    for s in (s16.get("signals") or [])[:25]:
        story.append(
            Paragraph(
                f"#{s.get('signal_id')} {s.get('product')} → {s.get('event')} "
                f"[{s.get('strength')}] PRR={s.get('prr')} WHO-UMC={s.get('who_umc')}",
                styles["Normal"],
            )
        )
    s17 = payload.get("section_17") or {}
    story.append(Spacer(1, 10))
    story.append(Paragraph(s17.get("title") or "Section 17", styles["Heading2"]))
    story.append(Paragraph(s17.get("risk_summary") or "", styles["Normal"]))
    story.append(Paragraph(s17.get("conclusion_draft") or "", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()
