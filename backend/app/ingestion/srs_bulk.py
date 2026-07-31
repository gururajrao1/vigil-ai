"""VAERS + FAERS quarterly bulk connectors (keyless, offline-first).

Tries optional public downloads when reachable; always falls back to bundled
fixture ICSRs so the pipeline never hard-requires a network or API key.

WHO VigiBase remains surrogate-only in the evidence registry.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

logger = logging.getLogger("vigilai.srs_bulk")

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_USER_AGENT = "VigilAI/1.0 (pharmacovigilance research; offline-first)"


def _load_json_fixture(name: str) -> list:
    path = _FIXTURE_DIR / name
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("fixture %s unreadable: %s", name, exc)
        return []


def _post_from_icrs(
    *,
    external_id: str,
    source: str,
    drug: str,
    reaction: str,
    body: str,
    country: str = "US",
    posted_at: Optional[datetime] = None,
    product_type: str = "drug",
    extra_title: str = "",
) -> dict:
    return {
        "external_id": external_id,
        "source": source,
        "platform": source,
        "author": f"{source}:{external_id}"[:64],
        "title": extra_title or f"{source.upper()}: {drug} → {reaction}",
        "body": body,
        "url": "",
        "posted_at": posted_at or datetime.utcnow(),
        "region": "North America",
        "country": country,
        "language": "en",
        "product_type": product_type,
    }


# --------------------------------------------------------------------------- #
# VAERS
# --------------------------------------------------------------------------- #
def crawl_vaers(limit: int = 40, *, force_fixture: bool = False) -> dict:
    """Ingest VAERS-style vaccine AE rows (CDC open data when reachable).

    Offline fixture always available under fixtures/vaers_sample.json.
    """
    posts: List[dict] = []
    mode = "fixture"

    if not force_fixture:
        try:
            import httpx

            # CDC Wonder / open VAERS CSV mirror — best-effort; may be blocked.
            url = (
                "https://vaers.hhs.gov/eSubDownload/index.jsp"
            )  # portal only; real bulk is zip
            # Prefer data.cdc.gov Socrata vaccine AE subset when present
            r = httpx.get(
                "https://data.cdc.gov/resource/mxun-zr5x.json",
                params={"$limit": min(limit, 50)},
                headers={"User-Agent": _USER_AGENT},
                timeout=10.0,
            )
            if r.status_code == 200 and isinstance(r.json(), list) and r.json():
                mode = "cdc_socrata"
                for i, row in enumerate(r.json()[:limit]):
                    vax = (
                        row.get("vax_name")
                        or row.get("vaccine_type")
                        or row.get("vax_type")
                        or "vaccine"
                    )
                    sym = (
                        row.get("symptom1")
                        or row.get("symptoms")
                        or row.get("symptom")
                        or "adverse event"
                    )
                    vaers_id = str(row.get("vaers_id") or row.get("id") or f"cdc-{i}")
                    posts.append(_post_from_icrs(
                        external_id=f"vaers:{vaers_id}",
                        source="vaers",
                        drug=str(vax).title(),
                        reaction=str(sym).lower(),
                        body=(
                            f"VAERS report {vaers_id}: patient received {vax}. "
                            f"Reported adverse event: {sym}. "
                            f"{row.get('symptom_text') or row.get('history') or ''}"
                        )[:2000],
                        country="US",
                        product_type="drug",
                        extra_title=f"VAERS: {vax} → {sym}",
                    ))
        except Exception as exc:
            logger.info("VAERS live fetch unavailable (%s) — using fixtures", exc)

    if not posts:
        mode = "fixture"
        for i, row in enumerate(_load_json_fixture("vaers_sample.json")[:limit]):
            posts.append(_post_from_icrs(
                external_id=row.get("external_id") or f"vaers:fix:{i}",
                source="vaers",
                drug=row.get("vaccine") or row.get("drug") or "vaccine",
                reaction=row.get("reaction") or "adverse event",
                body=row.get("body") or "",
                country=row.get("country") or "US",
                posted_at=_parse_dt(row.get("posted_at")),
            ))

    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts[:limit]),
        "mode": mode,
        "source": "vaers",
        "note": (
            "VAERS connector is keyless. Live CDC endpoints degrade to bundled "
            "fixtures. Vaccine AESI review remains in Analytic Lenses."
        ),
    }


# --------------------------------------------------------------------------- #
# FAERS quarterly bulk (ASCII subset)
# --------------------------------------------------------------------------- #
def crawl_faers_bulk(limit: int = 50, *, force_fixture: bool = False) -> dict:
    """Ingest a FAERS quarterly ASCII-style subset (fixture + optional download).

    Full quarterly zips are large; this connector loads a curated ASCII DEMO/DRUG/REAC
    slice from fixtures, with an optional openFDA multi-page pull as enrichment.
    """
    posts: List[dict] = []
    mode = "fixture"

    if not force_fixture:
        try:
            import httpx

            r = httpx.get(
                "https://api.fda.gov/drug/event.json",
                params={"search": "serious:1", "limit": min(limit, 100)},
                headers={"User-Agent": _USER_AGENT},
                timeout=12.0,
            )
            if r.status_code == 200:
                mode = "openfda_bulk_slice"
                for event in r.json().get("results", [])[:limit]:
                    safetyid = event.get("safetyreportid") or ""
                    drugs = event.get("patient", {}).get("drug", []) or []
                    reactions = event.get("patient", {}).get("reaction", []) or []
                    drug_names = [
                        (d.get("medicinalproduct") or "").title()
                        for d in drugs if d.get("medicinalproduct")
                    ]
                    rx_names = [
                        (x.get("reactionmeddrapt") or "").lower()
                        for x in reactions if x.get("reactionmeddrapt")
                    ]
                    if not drug_names or not rx_names:
                        continue
                    # Preserve polypharmacy in body for DDI mining
                    drug_str = ", ".join(drug_names[:6])
                    rx_str = ", ".join(rx_names[:6])
                    posts.append(_post_from_icrs(
                        external_id=f"faers_bulk:{safetyid}",
                        source="faers_bulk",
                        drug=drug_names[0],
                        reaction=rx_names[0],
                        body=(
                            f"FAERS bulk ICSR {safetyid}. Suspect/concomitant products: "
                            f"{drug_str}. Reactions: {rx_str}. "
                            f"Serious={event.get('serious')}."
                        )[:2000],
                        country=event.get("occurcountry") or "US",
                    ))
        except Exception as exc:
            logger.info("FAERS bulk live slice unavailable (%s) — fixtures", exc)

    if not posts:
        mode = "fixture"
        for i, row in enumerate(_load_json_fixture("faers_bulk_sample.json")[:limit]):
            drugs = row.get("drugs") or [row.get("drug") or "unknown"]
            reactions = row.get("reactions") or [row.get("reaction") or "adverse event"]
            posts.append(_post_from_icrs(
                external_id=row.get("external_id") or f"faers_bulk:fix:{i}",
                source="faers_bulk",
                drug=drugs[0],
                reaction=reactions[0],
                body=row.get("body") or (
                    f"FAERS quarterly fixture. Products: {', '.join(drugs)}. "
                    f"Reactions: {', '.join(reactions)}."
                ),
                country=row.get("country") or "US",
                posted_at=_parse_dt(row.get("posted_at")),
            ))

    return {
        "posts": posts[:limit],
        "unique_fetched": len(posts[:limit]),
        "mode": mode,
        "source": "faers_bulk",
        "note": (
            "FAERS bulk connector uses openFDA slices or bundled quarterly ASCII "
            "fixtures. Full FDA FAERS ASCII zips can be dropped into fixtures later."
        ),
    }


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except Exception:
        return datetime.utcnow()
