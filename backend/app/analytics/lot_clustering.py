"""Lot-level & supply-chain anomaly clustering (ecotoxicovigilance lite).

Extracts lot/batch/expiry cues from unstructured text and computes a
lot_clustering_coefficient. Concentrated spikes → MANUFACTURING_LOT_DEFECT
rather than systemic drug toxicity. Offline-first; optional openFDA enforcement
enrichment when reachable.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Optional

_DISCLAIMER = (
    "Lot/batch clustering. Lot extraction is heuristic NLP over social/"
    "MAUDE-like text; manufacturing flags are triage aids, not confirmed GMP findings."
)

# Common lot / batch / NDC-ish patterns
_LOT_RE = re.compile(
    r"\b(?:lot|batch|lot\s*no\.?|batch\s*no\.?|lot#|batch#)\s*[:#]?\s*([A-Z0-9][-A-Z0-9]{3,18})\b"
    r"|\b(LOT[-_]?[A-Z0-9]{4,18})\b"
    r"|\b(BATCH[-_]?[A-Z0-9]{4,18})\b",
    re.I,
)
_NDC_RE = re.compile(r"\b(\d{4,5}-\d{3,4}-\d{1,2})\b")
_EXP_RE = re.compile(
    r"\b(?:exp(?:iry|iration)?|expires?|use\s*by)\s*[:#]?\s*"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}(?:-\d{2})?|[A-Za-z]{3}\s*\d{4})",
    re.I,
)
_PACK_RE = re.compile(
    r"\b(blister|bottle|vial|syringe|pen\s*injector|sachet|carton|packaging)\b",
    re.I,
)
_CONTAM_RE = re.compile(
    r"\b(ndma|nitrosamine|contaminat(?:ion|ed)|impurit(?:y|ies)|particulate|"
    r"glass\s*shard|wrong\s*dose|mislabel(?:l?ed|ing)?|recall)\b",
    re.I,
)


def extract_lot_cues(text: str) -> dict:
    """Parse lot numbers, NDC-like codes, expiry, packaging, contamination cues."""
    text = text or ""
    lots = []
    for m in _LOT_RE.finditer(text):
        val = next((g for g in m.groups() if g), None)
        if val:
            lots.append(val.upper())
    ndcs = [m.group(1) for m in _NDC_RE.finditer(text)]
    exps = [m.group(1) for m in _EXP_RE.finditer(text)]
    packs = sorted({m.group(1).lower() for m in _PACK_RE.finditer(text)})
    contam = sorted({m.group(1).lower() for m in _CONTAM_RE.finditer(text)})
    return {
        "lots": lots,
        "ndcs": ndcs,
        "expiries": exps,
        "packaging": packs,
        "contamination_cues": contam,
    }


def lot_clustering_coefficient(lot_counts: Counter | dict) -> float:
    """Share of AE mentions concentrated in the dominant lot (0–1)."""
    if not lot_counts:
        return 0.0
    total = sum(int(v) for v in lot_counts.values())
    if total <= 0:
        return 0.0
    top = max(int(v) for v in lot_counts.values())
    return round(top / total, 4)


def assess_lot_clustering(
    texts: Iterable[str],
    *,
    product: str = "",
    spike: bool = False,
    threshold: float = 0.80,
) -> dict:
    """Aggregate lot extraction across posts and flag manufacturing defects."""
    lot_counter: Counter = Counter()
    ndc_counter: Counter = Counter()
    pack_counter: Counter = Counter()
    contam_counter: Counter = Counter()
    n_with_lot = 0
    n_docs = 0
    for raw in texts:
        n_docs += 1
        cues = extract_lot_cues(raw or "")
        if cues["lots"]:
            n_with_lot += 1
            lot_counter.update(cues["lots"])
        ndc_counter.update(cues["ndcs"])
        pack_counter.update(cues["packaging"])
        contam_counter.update(cues["contamination_cues"])

    coef = lot_clustering_coefficient(lot_counter)
    top_lot, top_n = (lot_counter.most_common(1)[0] if lot_counter else (None, 0))
    manufacturing = bool(coef >= threshold and top_n >= 3 and (spike or n_with_lot >= 3))
    # Contamination + recall language without multi-lot spread also raises flag
    if not manufacturing and contam_counter and coef >= 0.6 and top_n >= 2:
        manufacturing = True

    # Nothing to show a reviewer unless narratives actually carried lot/batch or
    # contamination language — otherwise the panel is empty filler.
    relevant = bool(n_with_lot or contam_counter or manufacturing)

    if manufacturing:
        interpretation = (
            f"≥{int(threshold * 100)}% of lot-tagged AEs concentrate in lot {top_lot} — "
            "prefer manufacturing / supply-chain investigation over systemic toxicity."
        )
    elif n_with_lot:
        interpretation = (
            f"{n_with_lot} of {n_docs} narratives named a lot/batch, spread across "
            f"{len(lot_counter)} lot(s) — no single lot dominates, so this still reads as a "
            "product-wide effect rather than one bad batch."
        )
    elif contam_counter:
        interpretation = (
            "Contamination or recall language appears without lot identifiers — worth "
            "checking enforcement reports, but not attributable to a batch yet."
        )
    else:
        interpretation = (
            "No lot, batch, or contamination cues in these narratives, so a manufacturing "
            "origin cannot be assessed from this text."
        )

    return {
        "product": product,
        "n_documents": n_docs,
        "n_with_lot": n_with_lot,
        "n_distinct_lots": len(lot_counter),
        "lot_counts": dict(lot_counter.most_common(20)),
        "ndc_counts": dict(ndc_counter.most_common(10)),
        "packaging_counts": dict(pack_counter.most_common(10)),
        "contamination_cues": dict(contam_counter.most_common(10)),
        "dominant_lot": top_lot,
        "dominant_lot_n": top_n,
        "lot_clustering_coefficient": coef,
        "threshold": threshold,
        "relevant": relevant,
        "flag": "MANUFACTURING_LOT_DEFECT" if manufacturing else None,
        "interpretation": interpretation,
        "disclaimer": _DISCLAIMER,
    }


def enrich_with_enforcement(product: str, *, offline_only: bool = False) -> dict:
    """Optional openFDA enforcement/recalls corroboration (offline empty OK)."""
    try:
        from ..evidence.recalls import query_recalls

        return query_recalls("drug", product, timeout=2.0) or {
            "available": False,
            "source": "openfda_enforcement_offline",
        }
    except TypeError:
        try:
            from ..evidence.recalls import query_recalls

            return query_recalls(product) or {
                "available": False,
                "source": "openfda_enforcement_offline",
            }
        except Exception:
            return {"available": False, "source": "openfda_enforcement_offline"}
    except Exception:
        return {"available": False, "source": "openfda_enforcement_offline"}

