"""Step 5 — multi-drug Story Stepper + ReportLab PDF handoff.

GET /api/story?event=X&drugs=A,B walks a 4-step validation carousel:
  1. Hypothesis
  2. Drug A metrics (cases, PRR, ROR, IC025, EBGM, severity)
  3. Drug B metrics
  4. LLM (or deterministic) one-paragraph evaluation
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..llm import generate
from ..models import Signal
from .scope import current_project_id

logger = logging.getLogger("vigilai.story")


def _severity_mix(sig: Signal) -> dict[str, Any]:
    """Best-effort severity mix from signal fields (single-row aggregate)."""
    sev = (sig.severity or "Unknown").title()
    return {
        "primary": sev,
        "who_umc": sig.who_umc,
        "who_umc_score": sig.who_umc_score,
        "sdr": bool(sig.sdr_flag),
        "strength": sig.strength,
        "distribution": {sev: int(sig.post_count or 0)},
    }


def _signal_metrics(sig: Optional[Signal]) -> dict[str, Any]:
    if not sig:
        return {
            "found": False,
            "cases": 0,
            "prr": None,
            "ror": None,
            "ic": None,
            "ic025": None,
            "ebgm": None,
            "eb05": None,
            "chi_square": None,
            "strength": None,
            "sdr": False,
            "severity_mix": None,
            "meddra_pt": None,
        }
    return {
        "found": True,
        "signal_id": sig.id,
        "drug": sig.drug,
        "event": sig.meddra_pt or sig.symptom,
        "cases": int(sig.post_count or 0),
        "prr": sig.prr,
        "prr_ci_low": sig.prr_ci_low,
        "prr_ci_high": sig.prr_ci_high,
        "ror": sig.ror,
        "ror_ci_low": sig.ror_ci_low,
        "ror_ci_high": sig.ror_ci_high,
        "ic": sig.ic,
        "ic025": sig.ic025,
        "ebgm": sig.ebgm,
        "eb05": sig.eb05,
        "chi_square": sig.chi_square,
        "strength": sig.strength,
        "sdr": bool(sig.sdr_flag),
        "severity_mix": _severity_mix(sig),
        "meddra_pt": sig.meddra_pt or sig.symptom,
        "drug_atc": sig.drug_atc,
    }


def _lookup_signal(
    db: Session,
    drug: str,
    event: str,
    project_id: Optional[int],
) -> Optional[Signal]:
    q = db.query(Signal).filter(Signal.drug.ilike(drug.strip()))
    # Match MedDRA PT or raw symptom
    from sqlalchemy import or_

    ev = event.strip()
    q = q.filter(or_(Signal.meddra_pt.ilike(ev), Signal.symptom.ilike(ev)))
    if project_id is not None:
        from sqlalchemy import or_ as _or

        q = q.filter(_or(Signal.project_id == project_id, Signal.project_id.is_(None), Signal.project_id == 0))
    return q.order_by(Signal.post_count.desc()).first()


def _deterministic_summary(event: str, drug_a: dict, drug_b: dict) -> str:
    a_name = drug_a.get("drug") or "Drug A"
    b_name = drug_b.get("drug") or "Drug B"
    a_prr = drug_a.get("prr")
    b_prr = drug_b.get("prr")
    a_ic = drug_a.get("ic025")
    b_ic = drug_b.get("ic025")
    a_sdr = "SDR" if drug_a.get("sdr") else "no SDR"
    b_sdr = "SDR" if drug_b.get("sdr") else "no SDR"

    def _cmp(metric: str, av, bv) -> str:
        if av is None and bv is None:
            return f"{metric} unavailable for both"
        if av is None:
            return f"{b_name} has {metric}={bv}"
        if bv is None:
            return f"{a_name} has {metric}={av}"
        if av > bv * 1.25:
            return f"{a_name} shows higher {metric} ({av} vs {bv})"
        if bv > av * 1.25:
            return f"{b_name} shows higher {metric} ({bv} vs {av})"
        return f"{metric} is comparable ({av} vs {bv})"

    parts = [
        f"Hypothesis evaluation for {event}: comparing {a_name} ({drug_a.get('cases', 0)} cases, {a_sdr}) "
        f"versus {b_name} ({drug_b.get('cases', 0)} cases, {b_sdr}).",
        _cmp("PRR", a_prr, b_prr) + ";",
        _cmp("IC025", a_ic, b_ic) + ";",
        _cmp("EBGM", drug_a.get("ebgm"), drug_b.get("ebgm")) + ".",
        "UMC-style interpretation treats IC025>0 as a signal of disproportionate reporting; "
        "this prototype summary is not for clinical decision-making.",
    ]
    return " ".join(parts)


def _llm_summary(event: str, drug_a: dict, drug_b: dict) -> tuple[str, str]:
    prompt = (
        "You are a pharmacovigilance signal analyst. Write ONE concise paragraph (max 120 words) "
        "comparing two drugs on the same adverse event using the metrics JSON. "
        "Mention PRR, ROR, IC025, EBGM, case counts, and whether IC025>0. "
        "Do not invent numbers. End with a caution that this is a prototype, not clinical advice.\n\n"
        f"Event: {event}\n"
        f"Drug A metrics: {json.dumps(drug_a, default=str)}\n"
        f"Drug B metrics: {json.dumps(drug_b, default=str)}\n"
    )
    text = None
    try:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(
                generate,
                prompt,
                "You are a senior PV epidemiologist. Be precise and cautious.",
                0.2,
                False,
            )
            text = fut.result(timeout=12.0)
    except Exception:
        text = None
    if text:
        return text.strip(), "llm"
    return _deterministic_summary(event, drug_a, drug_b), "deterministic"


def build_story(
    db: Session,
    *,
    event: str,
    drugs: list[str],
    project_id: Optional[int] = None,
) -> dict[str, Any]:
    if project_id is None:
        project_id = current_project_id()
    drugs = [d.strip() for d in drugs if d and d.strip()]
    if len(drugs) < 2:
        raise ValueError("Provide at least two drugs (comma-separated)")
    if not event or not event.strip():
        raise ValueError("event is required")

    event = event.strip()
    drug_a_name, drug_b_name = drugs[0], drugs[1]
    sig_a = _lookup_signal(db, drug_a_name, event, project_id)
    sig_b = _lookup_signal(db, drug_b_name, event, project_id)
    metrics_a = _signal_metrics(sig_a)
    metrics_b = _signal_metrics(sig_b)
    if not metrics_a.get("drug"):
        metrics_a["drug"] = drug_a_name
    if not metrics_b.get("drug"):
        metrics_b["drug"] = drug_b_name

    # Optional confounding adjustment (logistic) when both signals exist
    confounding = None
    try:
        from .confounding import adjust_pair_for_confounding

        confounding = adjust_pair_for_confounding(db, drug_a_name, drug_b_name, event, project_id)
    except Exception as exc:
        logger.debug("Confounding adjustment skipped: %s", exc)

    summary, summary_source = _llm_summary(event, metrics_a, metrics_b)

    hypothesis = (
        f"H1: Among reports mentioning {event}, {drug_a_name} exhibits a stronger "
        f"disproportionate reporting profile (PRR / ROR / IC025 / EBGM) than {drug_b_name}."
    )

    chart = [
        {
            "metric": "PRR",
            "drug_a": metrics_a.get("prr") or 0,
            "drug_b": metrics_b.get("prr") or 0,
        },
        {
            "metric": "ROR",
            "drug_a": metrics_a.get("ror") or 0,
            "drug_b": metrics_b.get("ror") or 0,
        },
        {
            "metric": "IC025",
            "drug_a": metrics_a.get("ic025") or 0,
            "drug_b": metrics_b.get("ic025") or 0,
        },
        {
            "metric": "EBGM",
            "drug_a": metrics_a.get("ebgm") or 0,
            "drug_b": metrics_b.get("ebgm") or 0,
        },
        {
            "metric": "Cases",
            "drug_a": metrics_a.get("cases") or 0,
            "drug_b": metrics_b.get("cases") or 0,
        },
    ]

    return {
        "event": event,
        "drugs": [drug_a_name, drug_b_name],
        "project_id": project_id,
        "steps": [
            {
                "step": 1,
                "title": "Hypothesis",
                "hypothesis": hypothesis,
                "null": (
                    f"H0: No meaningful difference in disproportionality for {event} "
                    f"between {drug_a_name} and {drug_b_name}."
                ),
            },
            {
                "step": 2,
                "title": f"{drug_a_name} metrics",
                "drug": drug_a_name,
                "metrics": metrics_a,
            },
            {
                "step": 3,
                "title": f"{drug_b_name} metrics",
                "drug": drug_b_name,
                "metrics": metrics_b,
            },
            {
                "step": 4,
                "title": "Evaluation summary",
                "summary": summary,
                "summary_source": summary_source,
                "confounding": confounding,
            },
        ],
        "chart": chart,
        "disclaimer": (
            "Prototype; synthetic/social data may be fictional; openFDA = US FAERS/MAUDE only; "
            "MedDRA coding is an open surrogate; not for clinical use."
        ),
    }


def story_pdf_bytes(payload: dict[str, Any]) -> bytes:
    """Compile the stepper history into a presentation-grade PDF via ReportLab."""
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
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "VigilTitle",
        parent=styles["Heading1"],
        textColor=colors.HexColor("#0f766e"),
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    h2 = ParagraphStyle("VigilH2", parent=styles["Heading2"], textColor=colors.HexColor("#134e4a"), spaceBefore=14)
    body = ParagraphStyle("VigilBody", parent=styles["BodyText"], alignment=TA_JUSTIFY, leading=14)
    small = ParagraphStyle("VigilSmall", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    story_flow = [
        Paragraph("VigilAI — Signal Validation Story", title_style),
        Paragraph(
            f"Event: <b>{payload.get('event')}</b> &nbsp;|&nbsp; "
            f"Drugs: <b>{' vs '.join(payload.get('drugs') or [])}</b>",
            body,
        ),
        Spacer(1, 8),
    ]

    for step in payload.get("steps") or []:
        story_flow.append(Paragraph(f"Step {step['step']}: {step['title']}", h2))
        if step["step"] == 1:
            story_flow.append(Paragraph(step.get("hypothesis") or "", body))
            story_flow.append(Paragraph(f"<i>{step.get('null') or ''}</i>", body))
        elif step["step"] in (2, 3):
            m = step.get("metrics") or {}
            rows = [
                ["Metric", "Value"],
                ["Cases", str(m.get("cases"))],
                ["PRR", str(m.get("prr"))],
                ["ROR", str(m.get("ror"))],
                ["IC025", str(m.get("ic025"))],
                ["EBGM", str(m.get("ebgm"))],
                ["EB05", str(m.get("eb05"))],
                ["Strength", str(m.get("strength"))],
                ["Severity", str((m.get("severity_mix") or {}).get("primary"))],
            ]
            t = Table(rows, colWidths=[2.2 * inch, 4 * inch])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#134e4a")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdfa")]),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story_flow.append(t)
        elif step["step"] == 4:
            story_flow.append(Paragraph(step.get("summary") or "", body))
            story_flow.append(
                Paragraph(f"Summary source: {step.get('summary_source')}", small)
            )

    story_flow.append(Spacer(1, 16))
    story_flow.append(Paragraph(payload.get("disclaimer") or "", small))
    doc.build(story_flow)
    return buf.getvalue()


def list_story_candidates(db: Session, project_id: Optional[int] = None, limit: int = 40) -> list[dict]:
    """Suggest event + drug pairs that have ≥2 *real products* sharing the same event.

    Filters out NER false positives where a symptom/condition (e.g. "acid reflux")
    was incorrectly stored in Signal.drug.
    """
    from collections import defaultdict

    from ..nlp.lexicons import BRAND_TO_GENERIC, CONDITIONS, DRUG_ATC, GENERIC_DRUGS, SYMPTOMS

    known_drugs = set(GENERIC_DRUGS) | set(BRAND_TO_GENERIC) | set(DRUG_ATC)
    known_non_drugs = set(SYMPTOMS) | set(CONDITIONS)

    def _is_product(name: str, product_type: Optional[str] = None) -> bool:
        key = (name or "").strip().lower()
        if not key or len(key) < 3:
            return False
        if key in known_non_drugs:
            return False
        if product_type == "device":
            return True
        if key in known_drugs:
            return True
        # Brand map values / multi-word generics already covered; reject free-text junk
        return False

    if project_id is None:
        project_id = current_project_id()
    q = db.query(Signal)
    if project_id is not None:
        from sqlalchemy import or_

        q = q.filter(or_(Signal.project_id == project_id, Signal.project_id.is_(None), Signal.project_id == 0))

    by_event: dict[str, list[Signal]] = defaultdict(list)
    for s in q.filter(Signal.post_count >= 1).all():
        ev = (s.meddra_pt or s.symptom or "").strip()
        if not ev or not s.drug:
            continue
        if not _is_product(s.drug, s.product_type):
            continue
        # Event itself should look like a phenotype, not a drug name alone
        if ev.lower() in known_drugs and ev.lower() not in known_non_drugs:
            continue
        by_event[ev].append(s)

    out = []
    for ev, rows in by_event.items():
        # Prefer higher case-count products as the default pair
        ranked = sorted(rows, key=lambda r: -(r.post_count or 0))
        drugs: list[str] = []
        seen: set[str] = set()
        for r in ranked:
            d = (r.drug or "").strip()
            key = d.lower()
            if key in seen:
                continue
            seen.add(key)
            drugs.append(d)
        if len(drugs) < 2:
            continue
        out.append({
            "event": ev,
            "drugs": drugs[:12],
            "pair": [drugs[0], drugs[1]],
            "n_drugs": len(drugs),
        })
    out.sort(key=lambda x: -x["n_drugs"])
    return out[:limit]
