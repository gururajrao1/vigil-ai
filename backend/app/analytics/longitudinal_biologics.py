"""Advanced therapies & biologics longitudinal surveillance (Cell/Gene & CAR-T).

Extends surveillance windows to 1–5 years and extracts CRS / ICANS / vector
integration onset cues from unstructured text. Deterministic offline-first —
no LSTM runtime dependency (sliding multi-year buckets replace deep models
when torch is unavailable).
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

_DISCLAIMER = (
    "Prototype advanced-therapy longitudinal surveillance. CRS/ICANS parsers and "
    "multi-year buckets are teaching surrogates — not validated CBER submissions."
)

# Product cues for cell/gene / CAR-T class
_ATMP_CUES = re.compile(
    r"\b(car-?t|car t|tisagenlecleucel|axicabtagene|brexucabtagene|lisocabtagene|"
    r"idecabtagene|ciltacabtagene|gene therapy|cell therapy|aav|lentiviral|"
    r"viral vector|atmp|advanced therapy)\b",
    re.I,
)

# Delayed biologic / ATMP event lexicon with typical latency bands (days)
_ONSET_PATTERNS: list[dict[str, Any]] = [
    {
        "id": "crs",
        "label": "Cytokine Release Syndrome (CRS)",
        "regex": re.compile(r"\b(cytokine release syndrome|\bcrs\b|cytokine storm)\b", re.I),
        "typical_onset_days": (0, 14),
        "severity_hint": "high",
    },
    {
        "id": "icans",
        "label": "ICANS",
        "regex": re.compile(
            r"\b(icans|immune effector cell.?associated neurotoxicity|"
            r"car.?t neurotoxicity|encephalopathy after car)\b",
            re.I,
        ),
        "typical_onset_days": (1, 30),
        "severity_hint": "high",
    },
    {
        "id": "vector_integration",
        "label": "Vector integration / insertional oncogenesis",
        "regex": re.compile(
            r"\b(insertional (oncogenesis|mutagenesis)|vector integration|"
            r"secondary malignancy after gene therapy|clonal expansion)\b",
            re.I,
        ),
        "typical_onset_days": (180, 1825),
        "severity_hint": "critical",
    },
    {
        "id": "hlh_mas",
        "label": "HLH / MAS",
        "regex": re.compile(r"\b(hlh|hemophagocytic|macrophage activation syndrome|\bmas\b)\b", re.I),
        "typical_onset_days": (0, 60),
        "severity_hint": "high",
    },
    {
        "id": "delayed_hypogamma",
        "label": "Delayed hypogammaglobulinemia",
        "regex": re.compile(r"\b(hypogammaglobulinemia|b-?cell aplasia|ivig dependent)\b", re.I),
        "typical_onset_days": (30, 730),
        "severity_hint": "moderate",
    },
]

_ONSET_DAY_RE = re.compile(
    r"(?:day|d)\s*[#:]?\s*(\d{1,4})"
    r"|(?:after|at|on)\s+(\d{1,4})\s*(?:days?|wks?|weeks?|months?|years?)"
    r"|(\d{1,4})\s*(?:days?|wks?|weeks?|months?|years?)\s+(?:after|post|following)",
    re.I,
)


def is_advanced_therapy(product: str, text: str = "") -> bool:
    blob = f"{product or ''} {text or ''}"
    return bool(_ATMP_CUES.search(blob))


def extract_onset_days(text: str) -> Optional[float]:
    """Best-effort time-to-onset in days from free text."""
    if not text:
        return None
    m = _ONSET_DAY_RE.search(text)
    if not m:
        return None
    raw = next((g for g in m.groups() if g), None)
    if raw is None:
        return None
    try:
        n = float(raw)
    except ValueError:
        return None
    span = m.group(0).lower()
    if "year" in span:
        return n * 365.0
    if "month" in span:
        return n * 30.4
    if "week" in span or "wk" in span:
        return n * 7.0
    return n


def parse_immunogenicity_events(text: str, *, product: str = "") -> list[dict]:
    """NLP-lite extractor for CRS/ICANS/vector events + onset."""
    hits = []
    onset = extract_onset_days(text or "")
    for pat in _ONSET_PATTERNS:
        if pat["regex"].search(text or ""):
            lo, hi = pat["typical_onset_days"]
            in_window = onset is None or (lo <= onset <= hi * 1.5)
            hits.append({
                "event_id": pat["id"],
                "label": pat["label"],
                "onset_days_extracted": onset,
                "typical_onset_days": [lo, hi],
                "onset_plausible": in_window,
                "severity_hint": pat["severity_hint"],
                "product_atmp": is_advanced_therapy(product, text),
            })
    return hits


def multi_year_buckets(
    dated_counts: Iterable[tuple[datetime, int]],
    *,
    years: int = 5,
    as_of: Optional[datetime] = None,
) -> dict:
    """Aggregate event counts into yearly post-index buckets (1..N years)."""
    years = max(1, min(int(years), 5))
    end = as_of or datetime.utcnow()
    start = end - timedelta(days=365 * years)
    buckets = {f"year_{i}": 0 for i in range(1, years + 1)}
    total = 0
    for ts, n in dated_counts:
        if ts is None:
            continue
        if ts < start or ts > end:
            continue
        age_days = (end - ts).total_seconds() / 86400.0
        # Map age to year bucket counting forward from oldest... use recency from start
        since_start = (ts - start).total_seconds() / 86400.0
        yr = min(years, max(1, int(since_start // 365) + 1))
        buckets[f"year_{yr}"] += int(n or 0)
        total += int(n or 0)

    # Simple trend: last year vs mean of prior
    vals = [buckets[f"year_{i}"] for i in range(1, years + 1)]
    prior = vals[:-1] or [0]
    mean_prior = sum(prior) / max(1, len(prior))
    latest = vals[-1] if vals else 0
    z = 0.0
    if mean_prior > 0:
        var = sum((v - mean_prior) ** 2 for v in prior) / max(1, len(prior))
        sd = math.sqrt(var) or 1.0
        z = (latest - mean_prior) / sd

    return {
        "window_years": years,
        "buckets": buckets,
        "total": total,
        "latest_year_count": latest,
        "mean_prior_years": round(mean_prior, 2),
        "latest_z": round(z, 2),
        "late_signal": bool(z >= 2 and latest >= 2),
        "disclaimer": _DISCLAIMER,
    }


def assess_signal_longitudinal(
    sig: Any,
    supporting_texts: Optional[list[str]] = None,
    dated_counts: Optional[list[tuple[datetime, int]]] = None,
) -> dict:
    """Attach ATMP / CRS-ICANS profile + multi-year trend for a signal."""
    product = getattr(sig, "drug", None) or (sig.get("drug") if isinstance(sig, dict) else "") or ""
    event = (
        getattr(sig, "meddra_pt", None)
        or getattr(sig, "symptom", None)
        or (sig.get("symptom") if isinstance(sig, dict) else "")
        or ""
    )
    texts = supporting_texts or []
    blob = " ".join(texts) + " " + event
    atmp = is_advanced_therapy(product, blob)
    immuno = []
    for t in texts[:40]:
        immuno.extend(parse_immunogenicity_events(t, product=product))
    # de-dupe by event_id keeping first
    seen = set()
    uniq = []
    for h in immuno:
        if h["event_id"] in seen:
            continue
        seen.add(h["event_id"])
        uniq.append(h)

    series = dated_counts or []
    windows = {
        f"{y}y": multi_year_buckets(series, years=y)
        for y in (1, 2, 3, 5)
    }
    return {
        "product": product,
        "event": event,
        "is_advanced_therapy": atmp,
        "immunogenicity_hits": uniq,
        "n_immunogenicity_mentions": len(immuno),
        "longitudinal_windows": windows,
        "flag": (
            "ATMP_DELAYED_TOXICITY_WATCH"
            if atmp and (uniq or (windows.get("5y") or {}).get("late_signal"))
            else None
        ),
        "disclaimer": _DISCLAIMER,
    }
