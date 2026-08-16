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


def _safe_json(raw: str | None, default):
    try:
        if raw is None or raw == "":
            return default
        return json.loads(raw)
    except Exception:
        return default


def signal_list_dict(s: Signal) -> dict:
    """Compact row for /api/signals list — skips heavy nested blobs (~10× smaller)."""
    regions = _safe_json(s.regions_json, {}) or {}
    if not isinstance(regions, dict):
        regions = {}
    primary_region = max(regions, key=regions.get) if regions else "Global"

    pgx = _safe_json(s.pgx_json, None)
    boxed = _safe_json(s.boxed_json, None)
    mechanism = _safe_json(s.mechanism_json, None)
    class_info = _safe_json(s.class_json, None)
    ac = _safe_json(s.active_comparator_json, None)
    spatial = _safe_json(s.spatial_json, None)
    vaccine = _safe_json(s.vaccine_json, None)
    label_gap = _safe_json(s.label_gap_json, None)
    maxsprt = _safe_json(s.maxsprt_json, None)
    fda = _safe_json(s.fda_evidence_json, {}) or {}

    def _slim(obj, keys):
        if not isinstance(obj, dict):
            return obj
        return {k: obj.get(k) for k in keys if k in obj}

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
        "severity": s.severity,
        "pgx_actionable": bool(s.pgx_actionable),
        "pgx": _slim(pgx, ("gene", "allele", "phenotype")) if pgx else None,
        "smq": _safe_json(s.smq_json, []) or [],
        "boxed_warning": bool(s.boxed_warning),
        "boxed": _slim(boxed, ("topics", "covers_event")) if boxed else None,
        "mechanism_plausible": bool(s.mechanism_plausible),
        "mechanism": _slim(mechanism, ("target_or_moa", "plausible")) if mechanism else None,
        "class_effect": bool(s.class_effect),
        "class_info": (
            {
                "class_name": class_info.get("class_name"),
                "member_drugs": (class_info.get("member_drugs") or [])[:8],
            }
            if isinstance(class_info, dict) else None
        ),
        "stands_out_in_class": bool(s.stands_out_in_class),
        "active_comparator": _slim(
            ac, ("ac_ror", "ac_ror_ci", "comparator_class")
        ) if ac else None,
        "is_vaccine": bool(s.is_vaccine),
        "aesi": s.aesi,
        "vaccine": (
            {
                "vaccine_name": vaccine.get("vaccine_name"),
                "brighton_level": vaccine.get("brighton_level"),
                "scri": _slim(vaccine.get("scri") or {}, ("ri",)),
            }
            if isinstance(vaccine, dict) else None
        ),
        "spatial_cluster": bool(s.spatial_cluster),
        "spatial": _slim(spatial, ("hotspot", "observed", "expected", "rr")) if spatial else None,
        "calibrated_p": s.calibrated_p,
        "calibrated_signal": bool(s.calibrated_signal),
        "e_value": s.e_value,
        "e_value_ci": s.e_value_ci,
        "br_verdict": s.br_verdict,
        "completeness": s.completeness,
        "well_documented": bool(s.well_documented),
        "fda_evidence": {
            "available": bool(fda.get("available")),
            "source": fda.get("source"),
            "report_count": fda.get("report_count"),
            "confidence_boost": fda.get("confidence_boost"),
        } if fda else None,
        "hr": s.hr,
        "hr_ci": _safe_json(s.hr_ci_json, None),
        "hr_p": s.hr_p,
        "hr_elevated": bool(s.hr_elevated),
        "maxsprt_llr": s.maxsprt_llr,
        "maxsprt_crossed": bool(s.maxsprt_crossed),
        "maxsprt": _slim(maxsprt, ("interpretation",)) if maxsprt else None,
        "label_novelty": s.label_novelty or "unknown",
        "label_gap": _slim(label_gap, ("note", "novelty_tier")) if label_gap else None,
        "review_state": s.review_state or "unreviewed",
        "trust_score": s.trust_score if s.trust_score is not None else 1.0,
        "trust_label": s.trust_label or "high",
        "detected_at": s.detected_at.isoformat() if s.detected_at else None,
        "lifecycle_status": s.lifecycle_status or "new",
        "priority_score": s.priority_score or 0.0,
    }


def signal_to_dict(s: Signal, fda: bool = True) -> dict:
    regions = _safe_json(s.regions_json, {}) or {}
    if not isinstance(regions, dict):
        regions = {}
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
        "who_umc_factors": _safe_json(s.who_umc_factors_json, []),
        "severity": s.severity,
        # pharmacogenomic risk overlay
        "pgx_actionable": bool(s.pgx_actionable),
        "pgx": _safe_json(s.pgx_json, None),
        # Standardised MedDRA Query (SMQ) syndrome membership
        "smq": _safe_json(s.smq_json, []),
        # FDA boxed (black-box) warning overlay
        "boxed_warning": bool(s.boxed_warning),
        "boxed": _safe_json(s.boxed_json, None),
        # mechanistic plausibility (Bradford Hill biological plausibility)
        "mechanism_plausible": bool(s.mechanism_plausible),
        "mechanism": _safe_json(s.mechanism_json, None),
        # class effect (ATC roll-up) + chemical read-across
        "class_effect": bool(s.class_effect),
        "class_info": _safe_json(s.class_json, None),
        "read_across": _safe_json(s.read_across_json, []),
        # active-comparator (same-class) disproportionality — confounding-by-indication control
        "stands_out_in_class": bool(s.stands_out_in_class),
        "active_comparator": _safe_json(s.active_comparator_json, None),
        # vaccine pharmacovigilance overlay (AESI / Brighton / SCRI surrogate)
        "is_vaccine": bool(s.is_vaccine),
        "aesi": s.aesi,
        "vaccine": _safe_json(s.vaccine_json, None),
        # spatial (geographic) cluster detection (Kulldorff-style scan statistic)
        "spatial_cluster": bool(s.spatial_cluster),
        "spatial": _safe_json(s.spatial_json, None),
        # empirical calibration (negative-control null) + E-values
        "calibrated_p": s.calibrated_p,
        "calibrated_signal": bool(s.calibrated_signal),
        "e_value": s.e_value,
        "e_value_ci": s.e_value_ci,
        "calibration": _safe_json(s.calibration_json, None),
        # quantitative benefit–risk (BRAT/MCDA + NNT vs NNH) — illustrative surrogate
        "br_verdict": s.br_verdict,
        "benefit_risk": _safe_json(s.benefit_risk_json, None),
        # UMC vigiGrade-style report completeness (documentation-quality surrogate)
        "completeness": s.completeness,
        "well_documented": bool(s.well_documented),
        "completeness_detail": _safe_json(s.completeness_json, None),
        "narrative": s.narrative,
        "narrative_source": s.narrative_source,
        "copilot": _safe_json(s.copilot_json, None),
        "copilot_source": s.copilot_source,
        "fda_evidence": _safe_json(s.fda_evidence_json, {}) if fda else None,
        # additional keyless evidence connectors
        "label_evidence": _safe_json(s.label_evidence_json, {}),
        "recall": _safe_json(s.recall_json, {}),
        "literature": _safe_json(s.literature_json, {}),
        "device_classification": _safe_json(s.device_class_json, {}),
        # Cox PH time-to-event surrogate (illustrative social-listening hazard ratio)
        "hr": s.hr,
        "hr_ci": _safe_json(s.hr_ci_json, None),
        "hr_p": s.hr_p,
        "hr_elevated": bool(s.hr_elevated),
        "hr_detail": _safe_json(s.hr_json, None),
        # MaxSPRT sequential surveillance (Kulldorff 2011) — type-I-error-controlled signal detection
        "maxsprt_llr": s.maxsprt_llr,
        "maxsprt_crossed": bool(s.maxsprt_crossed),
        "maxsprt": _safe_json(s.maxsprt_json, None),
        # labeling-gap detection (DailyMed adverse-reaction classification)
        "label_novelty": s.label_novelty or "unknown",
        "label_gap": _safe_json(s.label_gap_json, None),
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
    from ..analytics.evidence_hierarchy import evidence_tier_for_platform

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
        "evidence_tier": evidence_tier_for_platform(raw.platform),
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


def _norm_sentiment(label: str | None) -> str:
    """Fold case so FAERS bridge 'negative' merges with social NLP 'NEGATIVE'."""
    raw = (label or "NEUTRAL").strip().upper()
    if raw in {"NEGATIVE", "POSITIVE", "NEUTRAL"}:
        return raw
    return "NEUTRAL"


def _fold_platform(platform: str | None) -> str:
    """Collapse noisy feed variants (google_news/…) into stable buckets for charts."""
    p = (platform or "unknown").strip() or "unknown"
    low = p.lower()
    if low.startswith("google_news"):
        return "google_news"
    if low.startswith("faers"):
        return "faers"
    if low.startswith("maude"):
        return "maude"
    if low in {"twitter", "x", "x_twitter"}:
        return "twitter"
    return p


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
    platform_counts = Counter(_fold_platform(raw.platform) for _, raw in rows)
    sentiment_counts = Counter(_norm_sentiment(p.sentiment_label) for p, _ in rows)
    region_counts = Counter((raw.region or "Global") for _, raw in rows)
    country_counts = Counter(raw.country for _, raw in rows if raw.country)
    language_counts = Counter((raw.lang_name or raw.lang or "English") for _, raw in rows)
    translated_count = sum(1 for _, raw in rows if raw.translated)

    # Full SOC counter (do NOT truncate here — Overview used to show
    # len(most_common(10)) and looked "frozen" at 10 forever).
    soc_counts = Counter(s.meddra_soc for s in signals if s.meddra_soc)
    try:
        from ..nlp.meddra import SOC as _MEDDRA_SOC_CATALOG

        soc_catalog_size = len(_MEDDRA_SOC_CATALOG)
    except Exception:
        soc_catalog_size = 27

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

    # Regulatory corpus breakdown — Overview "Posts ingested" is raw_posts only;
    # OMOP FAERS staging can grow without moving that counter (common confusion).
    faers_posts = raw_q.filter(RawPost.platform.in_(("faers", "faers_bulk", "faers_live"))).count()
    maude_posts = raw_q.filter(RawPost.platform.in_(("maude", "maude_live"))).count()
    social_posts = max(0, total_raw - faers_posts - maude_posts)
    omop_persons = omop_drugs = omop_conditions = None
    try:
        from sqlalchemy import text as sa_text

        omop_persons = db.execute(sa_text("SELECT COUNT(*) FROM omop_person")).scalar()
        omop_drugs = db.execute(sa_text("SELECT COUNT(*) FROM omop_drug_exposure")).scalar()
        omop_conditions = db.execute(
            sa_text("SELECT COUNT(*) FROM omop_condition_occurrence")
        ).scalar()
    except Exception:
        pass

    critical_n = int(severity_counts.get("Critical") or 0)
    high_n = int(severity_counts.get("High") or 0)
    region_n = len(region_counts)
    non_english = sum(v for k, v in language_counts.items() if (k or "").lower() not in {"english", "en", ""})

    return {
        "total_posts": total_raw,
        "processed_posts": total_processed,
        "ae_posts": ae_posts,
        "ae_rate": round(ae_posts / total_processed, 3) if total_processed else 0.0,
        "signal_count": len(signals),
        "alert_count": alert_q.count(),
        "spike_count": spikes,
        "translated_posts": translated_count,
        "non_english_posts": non_english,
        "country_count": len(country_counts),
        "language_count": len(language_counts),
        "region_count": region_n,
        "soc_count": len(soc_counts),
        "soc_catalog_size": soc_catalog_size,
        "priority_signals": critical_n + high_n,
        "strength_distribution": dict(strength_counts),
        "severity_distribution": dict(severity_counts),
        "platform_distribution": dict(platform_counts.most_common(16)),
        "sentiment_distribution": dict(sentiment_counts),
        "region_distribution": dict(region_counts),
        "country_distribution": dict(country_counts.most_common(12)),
        "language_distribution": dict(language_counts.most_common(16)),
        # Full map for accurate soc_count; charts should slice client-side.
        "soc_distribution": dict(soc_counts),
        "top_drugs": top_drugs.most_common(8),
        "top_symptoms": top_symptoms.most_common(8),
        "top_platforms": platform_counts.most_common(8),
        "project_id": project_id,
        "regulatory": {
            "faers_posts": faers_posts,
            "maude_posts": maude_posts,
            "social_posts": social_posts,
            "omop_person": omop_persons,
            "omop_drug_exposure": omop_drugs,
            "omop_condition_occurrence": omop_conditions,
            "note": (
                "Overview Posts ingested = total_posts (raw_posts). "
                "Translated posts only rise when social NLP marks translated=true "
                "(FAERS/MAUDE ICSRs are English regulatory narratives). "
                "region_count caps at the macro-region taxonomy (~7); use country_count "
                "for geographic growth. soc_count is distinct MedDRA SOCs on Signal rows."
            ),
        },
        "metric_notes": {
            "translated_posts": "Social-listening NLP only; FAERS/MAUDE bulk bridges set translated=false.",
            "region_count": "Macro-region buckets (typically ≤7); grows with countries, not region labels.",
            "soc_count": "Distinct MedDRA SOC labels on recomputed Signal rows (catalog ≈27).",
            "priority_signals": "Critical + High severity from WHO-UMC grade_severity.",
        },
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
        if _norm_sentiment(p.sentiment_label) == "NEGATIVE":
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
