"""Step 5 — Surveillance Discrepancy Engine (social vs openFDA FAERS trends)."""
from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
import numpy as np
from scipy import stats
from sqlalchemy.orm import Session

from ..analytics.disproportionality import compute_signals
from ..config import settings
from ..evidence.fda import _offline_lookup, query_openfda
from ..models import ProcessedPost, RawPost, Signal
from ..nlp.lexicons import normalize_drug

logger = logging.getLogger("vigilai.divergence")

_Z_SPIKE = 2.0  # z-score threshold for divergence alert


def _daily_buckets(rows: list[tuple[datetime, str, str]], days: int = 90) -> dict[str, dict[str, int]]:
    """Bucket (date, drug, symptom) counts."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for posted_at, drug, symptom in rows:
        if posted_at < cutoff:
            continue
        day = posted_at.strftime("%Y-%m-%d")
        key = f"{drug}|{symptom}"
        buckets[day][key] += 1
    return buckets


def _social_timeline(
    db: Session,
    project_id: int,
    drug: str,
    symptom: str,
    days: int = 90,
) -> list[dict[str, Any]]:
    """Daily social AE mention counts for a drug–symptom pair within a project."""
    drug_n = normalize_drug(drug)
    sym = symptom.strip().lower()
    rows = (
        db.query(RawPost.posted_at, ProcessedPost.entities_json)
        .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
        .filter(
            RawPost.project_id == project_id,
            ProcessedPost.ae_flag.is_(True),
        )
        .all()
    )
    counts: Counter[str] = Counter()
    cutoff = datetime.utcnow() - timedelta(days=days)
    for posted_at, entities_json in rows:
        if not posted_at or posted_at < cutoff:
            continue
        try:
            entities = json.loads(entities_json or "{}")
        except json.JSONDecodeError:
            continue
        drugs = {normalize_drug(d.get("normalized", "")) for d in entities.get("drugs", [])}
        syms = {(s.get("normalized") or "").lower() for s in entities.get("symptoms", [])}
        if drug_n in drugs and sym in syms:
            counts[posted_at.strftime("%Y-%m-%d")] += 1

    return [{"date": d, "count": counts.get(d, 0)} for d in sorted(counts.keys())]


def _flat_faers_timeline(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Zero baseline when neither openFDA nor offline KB has signal."""
    timeline: list[dict[str, Any]] = []
    d = start
    while d <= end:
        timeline.append({"date": d.strftime("%Y-%m-%d"), "count": 0})
        d += timedelta(days=7)
    return timeline


def _offline_kb_timeline(
    drug: str,
    symptom: str,
    start: datetime,
    end: datetime,
    evidence: dict,
) -> list[dict[str, Any]]:
    """Synthesize a stable weekly FAERS-like curve from the offline KB report_count."""
    total = int(evidence.get("report_count") or 0)
    if total <= 0:
        return _flat_faers_timeline(start, end)

    weeks: list[datetime] = []
    d = start
    while d <= end:
        weeks.append(d)
        d += timedelta(days=7)
    if not weeks:
        weeks = [start]

    # Deterministic spread: hash drug|symptom|week index → slight variation around mean
    drug_n = normalize_drug(drug)
    sym = symptom.strip().lower()
    mean = total / len(weeks)
    timeline: list[dict[str, Any]] = []
    running = 0
    for i, week in enumerate(weeks):
        seed = hash(f"{drug_n}|{sym}|{i}") % 1000
        jitter = 0.7 + (seed / 1000) * 0.6  # 0.7–1.3×
        count = int(round(mean * jitter))
        if i == len(weeks) - 1:
            count = max(0, total - running)
        else:
            count = min(count, max(0, total - running))
        running += count
        timeline.append({"date": week.strftime("%Y-%m-%d"), "count": count})
    return timeline


def _faers_timeline(drug: str, symptom: str, days: int = 90) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Query openFDA FAERS; fall back to offline KB, then flat zero baseline."""
    drug_n = normalize_drug(drug)
    sym = symptom.strip().lower()
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    meta: dict[str, Any] = {"source": "flat_baseline", "available": False, "report_count": 0}

    try:
        params: dict[str, Any] = {
            "search": (
                f'patient.drug.medicinalproduct:"{drug_n}" AND '
                f'patient.reaction.reactionmeddrapt:"{sym}" AND '
                f'receivedate:[{start.strftime("%Y%m%d")} TO {end.strftime("%Y%m%d")}]'
            ),
            "count": "receivedate",
        }
        if settings.openfda_api_key:
            params["api_key"] = settings.openfda_api_key
        url = f"{settings.openfda_base_url}/drug/event.json"
        with httpx.Client(timeout=12.0) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                results = r.json().get("results", [])
                timeline: list[dict[str, Any]] = []
                for item in results:
                    term = str(item.get("term", ""))
                    if len(term) == 8 and term.isdigit():
                        timeline.append({
                            "date": f"{term[:4]}-{term[4:6]}-{term[6:8]}",
                            "count": int(item.get("count", 0)),
                        })
                if timeline:
                    timeline.sort(key=lambda x: x["date"])
                    total = sum(p["count"] for p in timeline)
                    return timeline, {
                        "source": "openfda",
                        "available": total > 0,
                        "report_count": total,
                    }
    except Exception as exc:
        logger.info("openFDA timeline unavailable, using offline KB: %s", exc)

    # Offline KB when live openFDA timeline is empty/unavailable
    evidence = query_openfda(drug_n, sym)
    if not evidence.get("available") and int(evidence.get("report_count") or 0) <= 0:
        kb = _offline_lookup(drug_n, sym)
        if kb.get("available") or int(kb.get("report_count") or 0) > 0:
            evidence = kb
    meta = {
        "source": evidence.get("source", "offline_kb"),
        "available": evidence.get("available", False),
        "report_count": evidence.get("report_count", 0),
        "match_score": evidence.get("match_score"),
    }
    if evidence.get("available") or evidence.get("report_count", 0) > 0:
        return _offline_kb_timeline(drug_n, sym, start, end, evidence), meta

    return _flat_faers_timeline(start, end), meta


def _align_series(
    social: list[dict[str, Any]],
    faers: list[dict[str, Any]],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    dates = sorted({p["date"] for p in social} | {p["date"] for p in faers})
    smap = {p["date"]: p["count"] for p in social}
    fmap = {p["date"]: p["count"] for p in faers}
    return dates, np.array([smap.get(d, 0) for d in dates], dtype=float), np.array(
        [fmap.get(d, 0) for d in dates], dtype=float
    )


def _zscore_latest(series: np.ndarray) -> float:
    if len(series) < 3:
        return 0.0
    hist = series[:-1]
    mu, sigma = float(np.mean(hist)), float(np.std(hist))
    if sigma < 1e-6:
        return 0.0
    return (float(series[-1]) - mu) / sigma


def compute_divergence(
    db: Session,
    project_id: int,
    drug: str,
    symptom: str,
    days: int = 90,
) -> dict[str, Any]:
    """Compare social listening vs FAERS timelines; flag sharp social spikes on flat FAERS."""
    social = _social_timeline(db, project_id, drug, symptom, days=days)
    faers, faers_meta = _faers_timeline(drug, symptom, days=days)
    dates, s_arr, f_arr = _align_series(social, faers)

    social_z = _zscore_latest(s_arr) if len(s_arr) else 0.0
    faers_z = _zscore_latest(f_arr) if len(f_arr) else 0.0
    social_slope = 0.0
    if len(s_arr) >= 4:
        x = np.arange(len(s_arr))
        social_slope = float(stats.linregress(x, s_arr).slope)

    divergent = social_z >= _Z_SPIKE and abs(faers_z) < 1.0 and float(np.mean(f_arr[-4:])) <= max(
        1.0, float(np.mean(f_arr)) * 1.1
    )

    alert_text = ""
    if divergent:
        alert_text = (
            f"TREND DIVERGENCE: Social mentions of {drug} → {symptom} spiked sharply "
            f"(z={social_z:.1f}) while official FAERS reporting remains flat "
            f"(recent mean={float(np.mean(f_arr[-4:])):.1f}). "
            "Requires clinical triangulation before regulatory action."
        )

    # Corpus disproportionality for the project (social-only ground truth)
    ae_rows = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(RawPost.project_id == project_id, ProcessedPost.ae_flag.is_(True))
        .all()
    )
    pair_counts: list[tuple[str, str]] = []
    for proc, raw in ae_rows:
        try:
            ent = json.loads(proc.entities_json or "{}")
        except json.JSONDecodeError:
            continue
        for d in ent.get("drugs", []):
            for s in ent.get("symptoms", []):
                pair_counts.append((
                    d.get("normalized", ""),
                    (s.get("normalized") or "").lower(),
                ))

    metrics: dict[str, Any] = {}
    if pair_counts:
        signals = compute_signals(pair_counts)
        match = next(
            (s for s in signals if normalize_drug(s["drug"]) == normalize_drug(drug)
             and (s["symptom"] or "").lower() == symptom.lower()),
            None,
        )
        if match:
            metrics = {
                "prr": match.get("prr"),
                "ror": match.get("ror"),
                "chi2": match.get("chi2"),
                "eb05": match.get("eb05"),
                "strength": match.get("strength"),
                "post_count": match.get("post_count"),
            }

    return {
        "drug": drug,
        "symptom": symptom,
        "project_id": project_id,
        "days": days,
        "social_timeline": social,
        "faers_timeline": faers,
        "faers_source": faers_meta.get("source", "flat_baseline"),
        "faers_evidence": faers_meta,
        "aligned_dates": dates,
        "social_z": round(social_z, 2),
        "faers_z": round(faers_z, 2),
        "social_slope": round(social_slope, 4),
        "divergent": divergent,
        "alert_text": alert_text,
        "disproportionality": metrics,
        "disclaimer": (
            "Prototype surveillance discrepancy view. Social data is unverified; "
            "openFDA reflects US FAERS only. Not for clinical or regulatory submission."
        ),
    }


def list_project_pairs(db: Session, project_id: int, limit: int = 20) -> list[dict[str, str]]:
    """Top drug–symptom pairs in a project for divergence UI pickers."""
    sigs = (
        db.query(Signal)
        .filter(Signal.project_id == project_id)
        .order_by(Signal.post_count.desc())
        .limit(limit)
        .all()
    )
    return [{"drug": s.drug, "symptom": s.meddra_pt or s.symptom} for s in sigs]
