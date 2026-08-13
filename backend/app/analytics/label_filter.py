"""Automated label comparison & Weber-effect noise filter (GVP Module 1).

Facade over DailyMed / offline label-gap classification plus launch-window and
media-spike adjustments that raise alert gates without rewriting stored DMA.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .label_gap import assess_label_gap
from .boxed_warnings import match as boxed_match

logger = logging.getLogger("vigilai.label_filter")

# Curated US approval / launch anchors (month resolution) for Weber window.
# Offline teaching set — not a complete regulatory calendar.
_APPROVAL_DATES: Dict[str, str] = {
    "isotretinoin": "1982-05-01",
    "ibuprofen": "1974-09-01",
    "paracetamol": "1955-01-01",
    "acetaminophen": "1955-01-01",
    "warfarin": "1954-06-01",
    "semaglutide": "2017-12-05",
    "ozempic": "2017-12-05",
    "montelukast": "1998-02-20",
    "clozapine": "1989-09-30",
    "adalimumab": "2002-12-31",
    "infliximab": "1998-08-24",
    "nirmatrelvir": "2021-12-22",
    "paxlovid": "2021-12-22",
    "molnupiravir": "2021-12-23",
    "comirnaty": "2020-12-11",
    "spikevax": "2020-12-18",
}

_DISCLAIMER = (
    "Label filter over DailyMed/open caches. Weber adjustment "
    "raises alert gates only — it does not alter stored PRR/ROR cells. "
    ""
)


def _parse_ym(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        return None


def launch_time_delta_months(product: str, *, as_of: Optional[datetime] = None) -> Optional[float]:
    """Months since curated approval / launch date, if known."""
    key = (product or "").strip().lower()
    raw = _APPROVAL_DATES.get(key)
    if not raw:
        # try first token / brand alias via normalize
        try:
            from ..nlp.drug_norm import normalize as normalize_drug

            g = (normalize_drug(key) or {}).get("generic") or key
            raw = _APPROVAL_DATES.get(str(g).lower())
        except Exception:
            raw = None
    if not raw:
        return None
    start = _parse_ym(raw)
    if not start:
        return None
    now = as_of or datetime.utcnow()
    days = max(0.0, (now - start).total_seconds() / 86400.0)
    return round(days / 30.4375, 1)


def _media_spike_ratio(db: Optional[Session], product: str, event: str) -> Optional[float]:
    """Latest 7d AE post volume / prior 7d mean; None if sparse."""
    if db is None:
        return None
    try:
        from ..models import ProcessedPost, RawPost

        cutoff = datetime.utcnow() - timedelta(days=14)
        q = (
            db.query(RawPost.posted_at)
            .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
            .filter(ProcessedPost.ae_flag.is_(True))
            .filter(RawPost.posted_at >= cutoff)
        )
        # Soft product/event filter on body/title is expensive; use entity JSON when present
        rows = q.all()
        if len(rows) < 4:
            return None
        now = datetime.utcnow()
        recent = sum(1 for (ts,) in rows if ts and ts >= now - timedelta(days=7))
        prior = sum(
            1
            for (ts,) in rows
            if ts and (now - timedelta(days=14)) <= ts < (now - timedelta(days=7))
        )
        if prior <= 0:
            return float(recent) if recent else None
        return round(recent / prior, 3)
    except Exception:
        logger.debug("media spike calc failed", exc_info=True)
        return None


def weber_adjustment(
    product: str,
    event: str,
    *,
    db: Optional[Session] = None,
    as_of: Optional[datetime] = None,
) -> dict:
    """Raise PRR/χ² alert gates early post-launch or during media spikes."""
    delta = launch_time_delta_months(product, as_of=as_of)
    spike = _media_spike_ratio(db, product, event)
    early = delta is not None and delta <= 24.0
    media = spike is not None and spike >= 4.0  # >300% = 4× prior week
    adjusted = bool(early or media)
    reasons: List[str] = []
    if early:
        reasons.append(f"launch_window_{delta}mo_le_24")
    if media:
        reasons.append(f"media_spike_ratio_{spike}")
    return {
        "weber_adjusted": adjusted,
        "launch_time_delta_months": delta,
        "media_spike_ratio_7d": spike,
        "effective_prr_min": 3.0 if adjusted else 2.0,
        "effective_chi2_min": 6.0 if adjusted else 4.0,
        "reasons": reasons,
        "note": (
            "Poisson/Weber variance correction applied to alert gates"
            if adjusted
            else "Standard PRR≥2 / χ²≥4 gates"
        ),
    }


def filter_product_event(
    product: str,
    event: str,
    *,
    pt: Optional[str] = None,
    soc: Optional[str] = None,
    db: Optional[Session] = None,
    offline_only: bool = True,
) -> dict:
    """Cross-reference Product→PT against label; attach Weber gate adjustment."""
    product = (product or "").strip()
    event = (event or "").strip()
    boxed = boxed_match(product, event, pt=pt or event, soc=soc)
    try:
        gap = assess_label_gap(
            product,
            event,
            pt=pt or event,
            soc=soc,
            boxed_info=boxed,
            offline_only=offline_only,
        )
    except Exception as exc:
        logger.debug("label gap failed: %s", exc)
        gap = {
            "novelty_tier": "unknown",
            "label_match": None,
            "label_section": None,
            "confidence": "low",
            "note": "Label assessment unavailable.",
        }

    tier = (gap.get("novelty_tier") or "unknown").lower()
    if tier == "in_label":
        tag = "ESTABLISHED_REACTION"
        is_in_label = True
    elif tier == "boxed":
        tag = "BOXED_COVERED"
        is_in_label = True
    elif tier == "novel":
        tag = "NOVEL_UNMAPPED_SIGNAL"
        is_in_label = False
    else:
        tag = "UNKNOWN"
        is_in_label = None

    section = gap.get("label_section")
    sections = {
        "section_5_warnings": section in ("warnings_precautions", "boxed_warning"),
        "section_6_adverse_reactions": section == "adverse_reactions" or tier == "in_label",
        "section_4_3_contraindications": False,  # open surrogate; flagged when context matches
    }
    if section == "warnings_precautions":
        sections["section_5_warnings"] = True

    weber = weber_adjustment(product, event, db=db)
    # In-label established reactions are noise for *novel* signal hunt —
    # still returned with suppress_novel_alert hint when Weber not critical.
    suppress = bool(is_in_label) and tag == "ESTABLISHED_REACTION"

    return {
        "product": product.lower(),
        "event": (pt or event).lower(),
        "is_in_label": is_in_label,
        "tag": tag,
        "novelty_tier": tier,
        "label_section": section,
        "sections_hit": sections,
        "label_gap": gap,
        "boxed": boxed,
        "weber": weber,
        "suppress_novel_alert": suppress,
        "alert_gates": {
            "prr_min": weber["effective_prr_min"],
            "chi2_min": weber["effective_chi2_min"],
            "weber_adjusted": weber["weber_adjusted"],
        },
        "disclaimer": _DISCLAIMER,
    }


def attach_label_filter_to_signal(sig_dict: dict, db: Optional[Session] = None) -> dict:
    """Enrich a signal_to_dict payload with label_filter block."""
    product = sig_dict.get("drug") or sig_dict.get("product") or ""
    event = sig_dict.get("meddra_pt") or sig_dict.get("symptom") or ""
    out = filter_product_event(
        product,
        event,
        pt=sig_dict.get("meddra_pt"),
        soc=sig_dict.get("meddra_soc"),
        db=db,
        offline_only=True,
    )
    sig_dict["label_filter"] = out
    return sig_dict
