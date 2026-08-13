"""GVP Module IX Signal Assessment Report (SAR) pack.

Produces Markdown and PDF assessment artifacts per signal: DMA table, case
series summary, label-gap, literature, openFDA corroboration, recommended next
action, reviewer + timestamps.

Aligned with EMA GVP Module IX signal-management documentation expectations.
"""
from __future__ import annotations

import io
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost, Signal


_DISCLAIMER = (
    "Prototype Signal Assessment Report (SAR). Synthetic/social data may be "
    "fictional; openFDA = US FAERS/MAUDE only; MedDRA coding is an open surrogate; "
    ""
)


def _safe_json(raw: Optional[str], default: Any = None):
    try:
        if not raw:
            return default
        return json.loads(raw)
    except Exception:
        return default


def _case_series_summary(db: Session, sig: Signal, limit: int = 8) -> list[dict]:
    ids = _safe_json(sig.supporting_post_ids, []) or []
    if not ids:
        return []
    rows = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.id.in_(ids[:limit]))
        .all()
    )
    out = []
    for proc, raw in rows:
        body = (raw.body or "")[:280]
        out.append({
            "post_id": proc.id,
            "source": raw.platform,
            "posted_at": raw.posted_at.isoformat() if raw.posted_at else None,
            "country": raw.country,
            "ae_confidence": proc.ae_confidence,
            "excerpt": body,
        })
    return out


def build_sar_payload(db: Session, sig: Signal) -> dict:
    """Structured SAR dict used by Markdown + PDF renderers."""
    fda = _safe_json(sig.fda_evidence_json, {}) or {}
    lit = _safe_json(sig.literature_json, {}) or {}
    label_gap = _safe_json(sig.label_gap_json, {}) or {}
    boxed = _safe_json(sig.boxed_json, {}) or {}
    mechanism = _safe_json(sig.mechanism_json, {}) or {}
    calib = _safe_json(sig.calibration_json, {}) or {}
    regions = _safe_json(sig.regions_json, {}) or {}

    # Recommended next action from lifecycle / strength heuristics
    status = (sig.lifecycle_status or "new").lower()
    if status in ("closed", "rejected"):
        action = f"Lifecycle terminal ({status}) — no further action unless reopened."
    elif sig.sdr_flag and (sig.label_novelty or "") == "novel":
        action = "Prioritise for assessment: SDR + labeling gap (novel vs label)."
    elif sig.sdr_flag:
        action = "Validate with case series review and openFDA/literature corroboration."
    elif (sig.strength or "").upper() == "MODERATE":
        action = "Continue monitoring; reassess after additional cases accumulate."
    else:
        action = "Routine surveillance; document if dismissed."

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "title": f"Signal Assessment Report — {sig.drug} / {sig.meddra_pt or sig.symptom}",
        "gvp_module": "EMA GVP Module IX (signal management) — documentation pack",
        "signal_id": sig.id,
        "product": {
            "name": sig.drug,
            "type": sig.product_type or "drug",
            "atc": sig.drug_atc,
            "gmdn": sig.device_gmdn,
            "imdrf": sig.imdrf_code,
        },
        "event": {
            "symptom": sig.symptom,
            "meddra_pt": sig.meddra_pt,
            "meddra_soc": sig.meddra_soc,
            "imdrf_term": sig.imdrf_term,
        },
        "detection": {
            "post_count": sig.post_count,
            "expected": sig.expected,
            "prr": sig.prr,
            "prr_ci": [sig.prr_ci_low, sig.prr_ci_high],
            "ror": sig.ror,
            "ror_ci": [sig.ror_ci_low, sig.ror_ci_high],
            "chi_square": sig.chi_square,
            "ic": sig.ic,
            "ic025": sig.ic025,
            "ebgm": sig.ebgm,
            "eb05": sig.eb05,
            "strength": sig.strength,
            "sdr_flag": bool(sig.sdr_flag),
        },
        "causality": {
            "who_umc": sig.who_umc,
            "who_umc_score": sig.who_umc_score,
            "factors": _safe_json(sig.who_umc_factors_json, []) or [],
            "severity": sig.severity,
        },
        "label_filter": None,
        "naranjo": None,
        "triangulation": None,
        "lifecycle": {
            "status": sig.lifecycle_status or "new",
            "priority_score": sig.priority_score,
            "owner": sig.lifecycle_owner,
            "notes": sig.lifecycle_notes,
            "updated_at": (
                sig.lifecycle_updated_at.isoformat() if sig.lifecycle_updated_at else None
            ),
        },
        "review": {
            "state": sig.review_state,
            "by": sig.reviewed_by,
            "at": sig.reviewed_at.isoformat() if sig.reviewed_at else None,
        },
        "label_gap": label_gap,
        "boxed_warning": boxed,
        "mechanism": mechanism,
        "fda_evidence": {
            "available": fda.get("available"),
            "source": fda.get("source"),
            "count": fda.get("count") or fda.get("total"),
            "note": fda.get("note"),
        },
        "literature": {
            "count": lit.get("count") or lit.get("n") or 0,
            "top_title": (lit.get("top") or lit.get("articles") or [{}]),
            "note": lit.get("note"),
        },
        "calibration": calib,
        "regions": regions,
        "narrative": sig.narrative,
        "case_series": _case_series_summary(db, sig),
        "recommended_action": action,
        "disclaimer": _DISCLAIMER,
    }

    # Enrich with Modules 1–3 (offline-safe)
    try:
        from .label_filter import filter_product_event
        from .triangulation import triangulate_signal
        from ..api.helpers import signal_to_dict
        from ..nlp.causality_engine import naranjo_score

        base = signal_to_dict(sig, fda=True)
        payload["label_filter"] = filter_product_event(
            sig.drug or "",
            sig.meddra_pt or sig.symptom or "",
            pt=sig.meddra_pt,
            soc=sig.meddra_soc,
            db=db,
            offline_only=True,
        )
        payload["triangulation"] = triangulate_signal(base, db=db)
        # Naranjo over concatenated case excerpts
        blob = " ".join(c.get("excerpt") or "" for c in payload.get("case_series") or [])
        payload["naranjo"] = naranjo_score(
            blob or (sig.narrative or ""),
            product=sig.drug or "",
            event=sig.meddra_pt or sig.symptom or "",
            fda_known=bool((fda or {}).get("known")),
        )
        if payload.get("naranjo"):
            payload["causality"]["naranjo"] = payload["naranjo"]
    except Exception:
        pass

    return payload


def render_sar_markdown(payload: dict) -> str:
    d = payload.get("detection") or {}
    c = payload.get("causality") or {}
    lc = payload.get("lifecycle") or {}
    prod = payload.get("product") or {}
    ev = payload.get("event") or {}
    lg = payload.get("label_gap") or {}
    fda = payload.get("fda_evidence") or {}
    lit = payload.get("literature") or {}

    lines = [
        f"# {payload.get('title')}",
        "",
        f"**Generated:** {payload.get('generated_at')}  ",
        f"**Framework:** {payload.get('gvp_module')}  ",
        f"**Signal ID:** {payload.get('signal_id')}",
        "",
        "> " + (payload.get("disclaimer") or _DISCLAIMER),
        "",
        "## 1. Identification",
        f"- **Product:** {prod.get('name')} ({prod.get('type')})"
        + (f" · ATC {prod.get('atc')}" if prod.get("atc") else ""),
        f"- **Event:** {ev.get('meddra_pt') or ev.get('symptom')}"
        + (f" · SOC {ev.get('meddra_soc')}" if ev.get("meddra_soc") else ""),
        "",
        "## 2. Detection (disproportionality)",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Reports (a) | {d.get('post_count')} |",
        f"| Expected | {d.get('expected')} |",
        f"| PRR (95% CI) | {d.get('prr')} ({(d.get('prr_ci') or [None, None])[0]}–{(d.get('prr_ci') or [None, None])[1]}) |",
        f"| ROR (95% CI) | {d.get('ror')} ({(d.get('ror_ci') or [None, None])[0]}–{(d.get('ror_ci') or [None, None])[1]}) |",
        f"| χ² (Yates) | {d.get('chi_square')} |",
        f"| IC / IC025 | {d.get('ic')} / {d.get('ic025')} |",
        f"| EBGM / EB05 | {d.get('ebgm')} / {d.get('eb05')} |",
        f"| Strength / SDR | {d.get('strength')} / {d.get('sdr_flag')} |",
        "",
        "## 3. Causality & seriousness",
        f"- **WHO-UMC:** {c.get('who_umc')} (score {c.get('who_umc_score')})",
        f"- **Factors:** {', '.join(c.get('factors') or []) or '—'}",
        f"- **Severity:** {c.get('severity')}",
        "",
        "## 4. Label gap & mechanism",
        f"- **Label novelty:** {lg.get('novelty_tier') or lg.get('novelty') or 'unknown'}",
        f"- **Boxed warning:** {bool(payload.get('boxed_warning'))}",
        f"- **Mechanism plausible:** {(payload.get('mechanism') or {}).get('plausible')}",
        "",
        "## 5. External corroboration",
        f"- **openFDA:** available={fda.get('available')} source={fda.get('source')} count={fda.get('count')}",
        f"- **Literature hits:** {lit.get('count')}",
        "",
        "## 6. Lifecycle & review (GVP IX)",
        f"- **Status:** {lc.get('status')} · priority {lc.get('priority_score')}",
        f"- **Owner:** {lc.get('owner') or '—'}",
        f"- **Notes:** {lc.get('notes') or '—'}",
        f"- **HCP review:** {(payload.get('review') or {}).get('state')} by {(payload.get('review') or {}).get('by') or '—'}",
        "",
        "## 7. Narrative",
        payload.get("narrative") or "_No narrative attached._",
        "",
        "## 8. Case series (supporting posts)",
    ]
    for i, cs in enumerate(payload.get("case_series") or [], 1):
        lines.append(
            f"{i}. [{cs.get('source')}] {cs.get('posted_at') or ''} "
            f"({cs.get('country') or 'n/a'}) — {cs.get('excerpt') or ''}"
        )
    if not payload.get("case_series"):
        lines.append("_No supporting posts stored._")

    lines.extend([
        "",
        "## 9. Recommended next action",
        payload.get("recommended_action") or "—",
        "",
        "---",
        f"_VigilAI SAR · {payload.get('generated_at')}_",
    ])
    return "\n".join(lines)


def render_sar_pdf(payload: dict) -> bytes:
    """ReportLab PDF; raises RuntimeError if reportlab missing."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:
        raise RuntimeError("reportlab is required for PDF export — pip install reportlab") from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "SarTitle", parent=styles["Heading1"], textColor=colors.HexColor("#0f766e"),
        alignment=TA_CENTER, fontSize=14, spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "SarH2", parent=styles["Heading2"], textColor=colors.HexColor("#134e4a"),
        fontSize=11, spaceBefore=10, spaceAfter=4,
    )
    body = ParagraphStyle("SarBody", parent=styles["BodyText"], alignment=TA_JUSTIFY, leading=13, fontSize=9)
    small = ParagraphStyle("SarSmall", parent=styles["Normal"], fontSize=7, textColor=colors.grey)

    d = payload.get("detection") or {}
    prod = payload.get("product") or {}
    ev = payload.get("event") or {}
    c = payload.get("causality") or {}
    lc = payload.get("lifecycle") or {}

    flow = [
        Paragraph("VigilAI — GVP Module IX Signal Assessment Report", title),
        Paragraph(payload.get("disclaimer") or _DISCLAIMER, small),
        Spacer(1, 6),
        Paragraph(
            f"<b>{prod.get('name')}</b> → <b>{ev.get('meddra_pt') or ev.get('symptom')}</b> "
            f"(signal #{payload.get('signal_id')})",
            body,
        ),
        Paragraph(f"Generated {payload.get('generated_at')}", small),
        Paragraph("Disproportionality", h2),
    ]

    rows = [
        ["Metric", "Value"],
        ["Reports", str(d.get("post_count"))],
        ["PRR", f"{d.get('prr')} ({(d.get('prr_ci') or [None, None])[0]}–{(d.get('prr_ci') or [None, None])[1]})"],
        ["ROR", f"{d.get('ror')}"],
        ["χ²", str(d.get("chi_square"))],
        ["IC025", str(d.get("ic025"))],
        ["EB05", str(d.get("eb05"))],
        ["Strength / SDR", f"{d.get('strength')} / {d.get('sdr_flag')}"],
        ["WHO-UMC", f"{c.get('who_umc')} ({c.get('severity')})"],
        ["Lifecycle", f"{lc.get('status')} · priority {lc.get('priority_score')}"],
    ]
    t = Table(rows, colWidths=[1.8 * inch, 4.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#134e4a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.Color(0.93, 0.96, 0.95)]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(t)

    flow.append(Paragraph("Recommended next action", h2))
    flow.append(Paragraph(payload.get("recommended_action") or "—", body))

    flow.append(Paragraph("Narrative", h2))
    flow.append(Paragraph((payload.get("narrative") or "No narrative.")[:1200], body))

    flow.append(Paragraph("Case series excerpts", h2))
    for cs in (payload.get("case_series") or [])[:6]:
        flow.append(Paragraph(
            f"• [{cs.get('source')}] {(cs.get('excerpt') or '')[:200]}",
            body,
        ))

    flow.append(Spacer(1, 12))
    flow.append(Paragraph(
        f"Reviewer: {(payload.get('review') or {}).get('by') or lc.get('owner') or 'unassigned'} · "
        f"Lifecycle owner notes: {(lc.get('notes') or '—')[:300]}",
        small,
    ))

    doc.build(flow)
    return buf.getvalue()
