"""Shared serialization helpers for API routes."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import List

from sqlalchemy.orm import Session

from ..models import Alert, ProcessedPost, RawPost, Signal


_COUNTRY_CODES = {
    "United States": "US", "Canada": "CA", "Germany": "DE", "United Kingdom": "GB",
    "France": "FR", "Italy": "IT", "India": "IN", "Japan": "JP", "Brazil": "BR",
    "Nigeria": "NG", "Australia": "AU",
}


def _normalize_gate_trace(raw_json: str | None) -> list:
    """Always return the AE gate list for UI (supports legacy list + nested payload)."""
    try:
        data = json.loads(raw_json or "[]")
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        gates = data.get("ae_gates")
        if isinstance(gates, list):
            return gates
    return []


def _gate_explainability(raw_json: str | None) -> dict:
    """Return explainability.gate_N payloads when stored on ProcessedPost."""
    try:
        data = json.loads(raw_json or "{}")
    except Exception:
        return {}
    if isinstance(data, dict):
        exp = data.get("explainability")
        if isinstance(exp, dict):
            return exp
    return {}


def signal_to_dict(s: Signal, fda: bool = True) -> dict:
    regions = json.loads(s.regions_json or "{}")
    primary_region = max(regions, key=regions.get) if regions else "Global"
    return {
        "id": s.id,
        "drug": s.drug,
        "symptom": s.symptom,
        "product_type": s.product_type or "drug",
        "drug_atc": s.drug_atc,
        "device_gmdn": s.device_gmdn,
        "imdrf_code": s.imdrf_code,
        "imdrf_term": s.imdrf_term,
        "meddra": {
            "pt": s.meddra_pt,
            "soc": s.meddra_soc,
            "soc_code": s.meddra_soc_code,
        },
        "regions": regions,
        "primary_region": primary_region,
        "post_count": s.post_count,
        "expected": s.expected,
        # disproportionality (frequentist + Bayesian)
        "prr": s.prr,
        "prr_ci": [s.prr_ci_low, s.prr_ci_high],
        "ror": s.ror,
        "ror_ci": [s.ror_ci_low, s.ror_ci_high],
        "chi_square": s.chi_square,
        "ic": s.ic,
        "ic025": s.ic025,
        "ebgm": s.ebgm,
        "eb05": s.eb05,
        "strength": s.strength,
        "sdr_flag": bool(s.sdr_flag),
        "trend_score": s.trend_score,
        "spike_flag": s.spike_flag,
        "spike_z": s.spike_z,
        "who_umc": s.who_umc,
        "who_umc_score": s.who_umc_score,
        "who_umc_factors": json.loads(s.who_umc_factors_json or "[]"),
        "severity": s.severity,
        # pharmacogenomic risk overlay
        "pgx_actionable": bool(s.pgx_actionable),
        "pgx": json.loads(s.pgx_json or "null"),
        # Standardised MedDRA Query (SMQ) syndrome membership
        "smq": json.loads(s.smq_json or "[]"),
        # FDA boxed (black-box) warning overlay
        "boxed_warning": bool(s.boxed_warning),
        "boxed": json.loads(s.boxed_json or "null"),
        # mechanistic plausibility (Bradford Hill biological plausibility)
        "mechanism_plausible": bool(s.mechanism_plausible),
        "mechanism": json.loads(s.mechanism_json or "null"),
        # class effect (ATC roll-up) + chemical read-across
        "class_effect": bool(s.class_effect),
        "class_info": json.loads(s.class_json or "null"),
        "read_across": json.loads(s.read_across_json or "[]"),
        # active-comparator (same-class) disproportionality — confounding-by-indication control
        "stands_out_in_class": bool(s.stands_out_in_class),
        "active_comparator": json.loads(s.active_comparator_json or "null"),
        # vaccine pharmacovigilance overlay (AESI / Brighton / SCRI surrogate)
        "is_vaccine": bool(s.is_vaccine),
        "aesi": s.aesi,
        "vaccine": json.loads(s.vaccine_json or "null"),
        # spatial (geographic) cluster detection (Kulldorff-style scan statistic)
        "spatial_cluster": bool(s.spatial_cluster),
        "spatial": json.loads(s.spatial_json or "null"),
        # empirical calibration (negative-control null) + E-values
        "calibrated_p": s.calibrated_p,
        "calibrated_signal": bool(s.calibrated_signal),
        "e_value": s.e_value,
        "e_value_ci": s.e_value_ci,
        "calibration": json.loads(s.calibration_json or "null"),
        # quantitative benefit–risk (BRAT/MCDA + NNT vs NNH) — illustrative surrogate
        "br_verdict": s.br_verdict,
        "benefit_risk": json.loads(s.benefit_risk_json or "null"),
        # UMC vigiGrade-style report completeness (documentation-quality surrogate)
        "completeness": s.completeness,
        "well_documented": bool(s.well_documented),
        "completeness_detail": json.loads(s.completeness_json or "null"),
        "narrative": s.narrative,
        "narrative_source": s.narrative_source,
        "copilot": json.loads(s.copilot_json or "null"),
        "copilot_source": s.copilot_source,
        "fda_evidence": json.loads(s.fda_evidence_json or "{}") if fda else None,
        # additional keyless evidence connectors
        "label_evidence": json.loads(s.label_evidence_json or "{}"),
        "recall": json.loads(s.recall_json or "{}"),
        "literature": json.loads(s.literature_json or "{}"),
        "device_classification": json.loads(s.device_class_json or "{}"),
        # Cox PH time-to-event surrogate (illustrative social-listening hazard ratio)
        "hr": s.hr,
        "hr_ci": json.loads(s.hr_ci_json or "null"),
        "hr_p": s.hr_p,
        "hr_elevated": bool(s.hr_elevated),
        "hr_detail": json.loads(s.hr_json or "null"),
        # MaxSPRT sequential surveillance (Kulldorff 2011) — type-I-error-controlled signal detection
        "maxsprt_llr": s.maxsprt_llr,
        "maxsprt_crossed": bool(s.maxsprt_crossed),
        "maxsprt": json.loads(s.maxsprt_json or "null"),
        # labeling-gap detection (DailyMed adverse-reaction classification)
        "label_novelty": s.label_novelty or "unknown",
        "label_gap": json.loads(s.label_gap_json or "null"),
        # review / detection metadata (KPIs)
        "review_state": s.review_state or "unreviewed",
        "reviewed_by": s.reviewed_by,
        "trust_score": s.trust_score if s.trust_score is not None else 1.0,
        "trust_label": s.trust_label or "high",
        "earliest_post_at": s.earliest_post_at.isoformat() if s.earliest_post_at else None,
        "detected_at": s.detected_at.isoformat() if s.detected_at else None,
        "first_seen": s.first_seen.isoformat() if s.first_seen else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        # GVP Module IX signal lifecycle
        "lifecycle_status": s.lifecycle_status or "new",
        "priority_score": s.priority_score or 0.0,
        "lifecycle_owner": s.lifecycle_owner,
        "lifecycle_notes": s.lifecycle_notes,
        "lifecycle_updated_at": s.lifecycle_updated_at.isoformat() if s.lifecycle_updated_at else None,
    }


def post_to_dict(p: ProcessedPost, raw: RawPost) -> dict:
    body = raw.body or ""
    # Live Feed should never dump multi-KB binary/PDF streams
    if body.lstrip().startswith("%PDF-") or "\x00" in body[:200]:
        preview = "[Binary/PDF content omitted — prefer HTML sources, or re-approve after PDF text extraction]"
    else:
        preview = body if len(body) <= 600 else body[:600].rstrip() + "…"
    return {
        "id": p.id,
        "raw_id": raw.id,
        "platform": raw.platform,
        "url": raw.url,
        "author_hash": raw.author_hash,
        "title": raw.title,
        "text": preview,
        "text_full_len": len(body),
        "text_original": (raw.body_original or "")[:400] or None,
        "lang": raw.lang,
        "lang_name": raw.lang_name,
        "translated": raw.translated,
        "region": raw.region,
        "country": raw.country,
        "posted_at": raw.posted_at.isoformat() if raw.posted_at else None,
        "pii_found": json.loads(raw.pii_found or "[]"),
        "entities": json.loads(p.entities_json or "{}"),
        "sentiment": {"label": p.sentiment_label, "score": p.sentiment_score},
        "negation": json.loads(p.negation_json or "{}"),
        "ae_flag": p.ae_flag,
        "ae_confidence": p.ae_confidence,
        "ae_reason": p.ae_reason,
        "gate_trace": _normalize_gate_trace(p.gate_trace_json),
        "explainability": _gate_explainability(p.gate_trace_json),
    }


def alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "signal_id": a.signal_id,
        "drug": a.drug,
        "symptom": a.symptom,
        "severity": a.severity,
        "message": a.message,
        "acknowledged": a.acknowledged,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _project_scope(col, project_id: int | None):
    """Include this project plus legacy rows with NULL/0 project_id."""
    from sqlalchemy import or_

    if project_id is None:
        return True
    return or_(col == project_id, col.is_(None), col == 0)


def dashboard_stats(db: Session, project_id: int | None = None) -> dict:
    raw_q = db.query(RawPost)
    if project_id is not None:
        raw_q = raw_q.filter(_project_scope(RawPost.project_id, project_id))
    total_raw = raw_q.count()

    proc_q = db.query(ProcessedPost).join(RawPost, ProcessedPost.raw_id == RawPost.id)
    if project_id is not None:
        proc_q = proc_q.filter(_project_scope(RawPost.project_id, project_id))
    total_processed = proc_q.count()
    ae_posts = proc_q.filter(ProcessedPost.ae_flag.is_(True)).count()

    sig_q = db.query(Signal)
    if project_id is not None:
        sig_q = sig_q.filter(_project_scope(Signal.project_id, project_id))
    signals = sig_q.all()
    strength_counts = Counter(s.strength for s in signals)
    severity_counts = Counter(s.severity for s in signals)
    spikes = sum(1 for s in signals if s.spike_flag)

    rows_q = db.query(ProcessedPost, RawPost).join(RawPost, ProcessedPost.raw_id == RawPost.id)
    if project_id is not None:
        rows_q = rows_q.filter(_project_scope(RawPost.project_id, project_id))
    rows = rows_q.all()
    platform_counts = Counter(raw.platform for _, raw in rows)
    sentiment_counts = Counter(p.sentiment_label for p, _ in rows)
    region_counts = Counter((raw.region or "Global") for _, raw in rows)
    country_counts = Counter(raw.country for _, raw in rows if raw.country)
    language_counts = Counter((raw.lang_name or "English") for _, raw in rows)
    translated_count = sum(1 for _, raw in rows if raw.translated)

    soc_counts = Counter(s.meddra_soc for s in signals if s.meddra_soc)

    top_drugs = Counter()
    top_symptoms = Counter()
    from ..nlp.text_normalize import fold_key, normalize_label
    drug_canon: dict[str, str] = {}
    sym_canon: dict[str, str] = {}
    for s in signals:
        d_raw = s.drug or ""
        dk = fold_key(d_raw)
        if dk and dk not in drug_canon:
            drug_canon[dk] = normalize_label(d_raw, kind="product") or d_raw
        if dk:
            top_drugs[drug_canon[dk]] += s.post_count
        s_raw = s.meddra_pt or s.symptom or ""
        sk = fold_key(s_raw)
        if sk and sk not in sym_canon:
            sym_canon[sk] = normalize_label(s_raw, kind="event") or s_raw
        if sk:
            top_symptoms[sym_canon[sk]] += s.post_count

    alert_q = db.query(Alert)
    if project_id is not None:
        alert_q = alert_q.filter(_project_scope(Alert.project_id, project_id))

    return {
        "total_posts": total_raw,
        "processed_posts": total_processed,
        "ae_posts": ae_posts,
        "ae_rate": round(ae_posts / total_processed, 3) if total_processed else 0.0,
        "signal_count": len(signals),
        "alert_count": alert_q.count(),
        "spike_count": spikes,
        "translated_posts": translated_count,
        "country_count": len(country_counts),
        "language_count": len(language_counts),
        "strength_distribution": dict(strength_counts),
        "severity_distribution": dict(severity_counts),
        "platform_distribution": dict(platform_counts),
        "sentiment_distribution": dict(sentiment_counts),
        "region_distribution": dict(region_counts),
        "country_distribution": dict(country_counts.most_common(12)),
        "language_distribution": dict(language_counts),
        "soc_distribution": dict(soc_counts.most_common(10)),
        "top_drugs": top_drugs.most_common(8),
        "top_symptoms": top_symptoms.most_common(8),
        "project_id": project_id,
    }


def overview_timeseries(db: Session, project_id: int | None = None) -> dict:
    """Daily AE volume, total volume, and sentiment split."""
    rows_q = db.query(ProcessedPost, RawPost).join(RawPost, ProcessedPost.raw_id == RawPost.id)
    if project_id is not None:
        rows_q = rows_q.filter(_project_scope(RawPost.project_id, project_id))
    rows = rows_q.all()
    daily_total = defaultdict(int)
    daily_ae = defaultdict(int)
    daily_neg = defaultdict(int)
    for p, raw in rows:
        d = (raw.posted_at or datetime.utcnow()).date().isoformat()
        daily_total[d] += 1
        if p.ae_flag:
            daily_ae[d] += 1
        if p.sentiment_label == "NEGATIVE":
            daily_neg[d] += 1

    dates = sorted(daily_total.keys())
    return {
        "series": [
            {
                "date": d,
                "total": daily_total[d],
                "ae": daily_ae[d],
                "negative": daily_neg[d],
            }
            for d in dates
        ],
        "project_id": project_id,
    }


def signal_trend_series(db: Session, sig: Signal) -> List[dict]:
    from ..analytics.trend import compute_trend

    ids = json.loads(sig.supporting_post_ids or "[]")
    if not ids:
        return []
    rows = (
        db.query(RawPost)
        .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.id.in_(ids))
        .all()
    )
    timestamps = [r.posted_at or datetime.utcnow() for r in rows]
    return compute_trend(timestamps)["series"]
