"""Pharmacogenomics & biomarker safety profiling engine.

Facade over the offline CPIC/PharmGKB curated table with optional live
PharmGKB (`https://api.pharmgkb.org/v1/`) and CPIC (`https://api.cpicpgx.org/v1/`)
lookups. Always degrades to the local cache — never hard-requires a key or network.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path
from typing import Any, Optional

from . import pgx as pgx_base

logger = logging.getLogger("vigilai.pgx_engine")

_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "pgx_cache"
_DISCLAIMER = (
    "Prototype PGx overlay. Offline CPIC/PharmGKB curated surrogate with optional "
    "live API enrichment. Not a clinical decision-support system."
)

PHARMGKB_BASE = "https://api.pharmgkb.org/v1"
CPIC_BASE = "https://api.cpicpgx.org/v1"


def _cache_path(key: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key.lower())[:120]
    return _CACHE_DIR / f"{safe}.json"


def _read_cache(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(key: str, payload: dict) -> None:
    try:
        _cache_path(key).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("pgx cache write failed: %s", exc)


def _http_json(url: str, timeout: float = 4.0) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "VigilAI/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.debug("pgx http miss %s: %s", url, exc)
        return None


def offline_match(drug: str, event: str, *, soc: Optional[str] = None) -> Optional[dict]:
    """Deterministic local CPIC/PharmGKB table match."""
    hit = pgx_base.match(drug, event, soc=soc)
    if not hit:
        return None
    return {
        **hit,
        "is_pgx_actionable": True,
        "badge": f"PGx WARNING: {hit.get('gene')} {hit.get('allele')} — {hit.get('phenotype')}",
        "level_badge": f"PGx ACTIONABLE: {hit.get('level') or 'CPIC/PharmGKB'}",
        "source_mode": "offline_table",
        "disclaimer": _DISCLAIMER,
    }


def fetch_pharmgkb(drug: str, *, offline_only: bool = False) -> dict:
    key = f"pharmgkb_{drug}"
    cached = _read_cache(key)
    if offline_only:
        return cached or {"available": False, "source": "pharmgkb_offline", "drug": drug}
    if cached and cached.get("available"):
        return cached
    # Search clinical annotations by drug name (best-effort public endpoint)
    from urllib.parse import quote

    url = f"{PHARMGKB_BASE}/data/clinicalAnnotation?drug.name={quote(drug)}"
    raw = _http_json(url)
    if not raw:
        out = cached or {"available": False, "source": "pharmgkb_offline", "drug": drug, "data": []}
        _write_cache(key, out)
        return out
    data = raw.get("data") if isinstance(raw, dict) else raw
    out = {
        "available": True,
        "source": "pharmgkb_live",
        "drug": drug,
        "n": len(data) if isinstance(data, list) else 1,
        "data": (data[:8] if isinstance(data, list) else data),
    }
    _write_cache(key, out)
    return out


def fetch_cpic(drug: str, *, offline_only: bool = False) -> dict:
    key = f"cpic_{drug}"
    cached = _read_cache(key)
    if offline_only:
        return cached or {"available": False, "source": "cpic_offline", "drug": drug}
    if cached and cached.get("available"):
        return cached
    from urllib.parse import quote

    url = f"{CPIC_BASE}/pair?drugname={quote(drug)}"
    raw = _http_json(url)
    if not raw:
        out = cached or {"available": False, "source": "cpic_offline", "drug": drug, "data": []}
        _write_cache(key, out)
        return out
    data = raw if isinstance(raw, list) else raw.get("data") or raw
    out = {
        "available": True,
        "source": "cpic_live",
        "drug": drug,
        "n": len(data) if isinstance(data, list) else 1,
        "data": (data[:8] if isinstance(data, list) else data),
    }
    _write_cache(key, out)
    return out


def get_pgx_gene_associations(drug_name: str, *, event: str = "", offline_only: bool = False) -> dict:
    """MCP / API entry: gene-variant warnings + metabolizer profiles for a drug."""
    local = offline_match(drug_name, event or "hypersensitivity") if event else None
    # Also try matching any table row for the drug alone (broader associations)
    broad: list[dict] = []
    for row in pgx_base.PGX_TABLE:
        drugs = {d.lower() for d in row.get("drugs") or []}
        g = (pgx_base.normalize_drug(drug_name) if hasattr(pgx_base, "normalize_drug") else None)
        from ..nlp.lexicons import normalize_drug

        nd = (normalize_drug(drug_name) or drug_name or "").lower()
        if nd in drugs or any(nd == d or d in nd for d in drugs):
            broad.append({
                "gene": row["gene"],
                "allele": row["allele"],
                "phenotype": row["phenotype"],
                "level": row.get("level"),
                "recommendation": row.get("recommendation"),
                "reactions": sorted(row.get("reactions") or [])[:12],
            })

    pharm = fetch_pharmgkb(drug_name, offline_only=offline_only)
    cpic = fetch_cpic(drug_name, offline_only=offline_only)
    actionable = bool(local) or bool(broad)
    return {
        "drug": drug_name,
        "event": event or None,
        "is_pgx_actionable": actionable,
        "match": local,
        "associations": broad,
        "pharmgkb": {"available": pharm.get("available"), "source": pharm.get("source"), "n": pharm.get("n")},
        "cpic": {"available": cpic.get("available"), "source": cpic.get("source"), "n": cpic.get("n")},
        "badge": (local or {}).get("level_badge") or (
            f"PGx ACTIONABLE: {broad[0]['gene']}" if broad else None
        ),
        "disclaimer": _DISCLAIMER,
    }


def profile_signal(drug: str, event: str, *, soc: Optional[str] = None, offline_only: bool = True) -> dict:
    """Enrich a Product→PT pair with PGx badges for Signal Detail.

    Only an event-matched hit counts as actionable — a drug-level association whose
    reaction set does not include this event is reported separately, so we never
    over-call PGx (e.g. codeine -> headache).
    """
    hit = offline_match(drug, event, soc=soc)
    assoc = get_pgx_gene_associations(drug, event=event, offline_only=offline_only)
    associations = assoc.get("associations") or []
    return {
        "is_pgx_actionable": bool(hit),
        "pgx": hit,
        "associations": associations,
        "has_other_associations": bool(associations) and not hit,
        "verdict": (
            f"Actionable PGx association for {drug} \u2192 {event}." if hit
            else (
                f"{drug} has known gene associations, but none map to {event}."
                if associations else
                f"No curated CPIC/PharmGKB association for {drug} \u2192 {event}."
            )
        ),
        "badge": (hit or {}).get("badge"),
        "level_badge": (hit or {}).get("level_badge"),
        "disclaimer": _DISCLAIMER,
    }
