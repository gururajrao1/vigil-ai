"""Concurrent multi-source evidence enrichment for signals.

Given the detected (drug/device, event) pairs, gather — in parallel, cached, with
short timeouts so recompute never hangs — real keyless evidence:

  * DailyMed label match          (per drug)
  * openFDA recall / enforcement  (per product)
  * openFDA device classification (per device)
  * PubMed literature             (per pair)

Per-product lookups are deduped so we issue far fewer network calls than there are
signals. Everything degrades to a deterministic offline result.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from ..config import settings
from .dailymed import query_dailymed
from .device_class import query_device_classification
from .pubmed import query_pubmed
from .recalls import query_recalls

Pair = Tuple[str, str]


def enrich_one(product_type: str, name: str, event: str, timeout: float = 4.0) -> dict:
    """Enrich a SINGLE (product, event) pair — used lazily on signal-detail view.

    At most 4 outbound calls (cached), so it never creates a rate-limit burst the
    way a bulk fan-out would. Every source degrades to a deterministic fallback.
    """
    if not settings.use_evidence_enrichment:
        return {}
    is_device = (product_type or "drug") == "device"
    out: dict = {"label_evidence": {"available": False},
                 "recall": {"available": False},
                 "literature": {"available": False},
                 "device_classification": {"available": False}}
    # small pool: 4 concurrent calls for one pair is safe + fast
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_recall = ex.submit(query_recalls, product_type, name, timeout)
        f_lit = ex.submit(query_pubmed, name, event, timeout)
        f_label = ex.submit(query_dailymed, name, timeout) if not is_device else None
        f_class = ex.submit(query_device_classification, name, timeout) if is_device else None
        try:
            out["recall"] = f_recall.result()
        except Exception:
            pass
        try:
            out["literature"] = f_lit.result()
        except Exception:
            pass
        if f_label is not None:
            try:
                out["label_evidence"] = f_label.result()
            except Exception:
                pass
        if f_class is not None:
            try:
                out["device_classification"] = f_class.result()
            except Exception:
                pass
    return out


def enrich_pairs(pairs: List[Tuple[str, str, str]], timeout: float = 3.0) -> Dict[Pair, dict]:
    """pairs: list of (product_type, product_name, event).

    Returns {(product, event): {label, recall, literature, device_classification}}.
    """
    if not settings.use_evidence_enrichment or not pairs:
        return {}

    drugs = {name for (pt, name, _e) in pairs if pt != "device"}
    devices = {name for (pt, name, _e) in pairs if pt == "device"}
    products = {(pt, name) for (pt, name, _e) in pairs}

    label_map: Dict[str, dict] = {}
    class_map: Dict[str, dict] = {}
    recall_map: Dict[Tuple[str, str], dict] = {}
    lit_map: Dict[Pair, dict] = {}

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {}
        for d in drugs:
            futs[ex.submit(query_dailymed, d, timeout)] = ("label", d)
        for dev in devices:
            futs[ex.submit(query_device_classification, dev, timeout)] = ("class", dev)
        for pt, name in products:
            futs[ex.submit(query_recalls, pt, name, timeout)] = ("recall", (pt, name))
        for pt, name, event in pairs:
            futs[ex.submit(query_pubmed, name, event, timeout)] = ("lit", (name, event))

        for fut in as_completed(futs):
            kind, keyref = futs[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            if res is None:
                continue
            if kind == "label":
                label_map[keyref] = res
            elif kind == "class":
                class_map[keyref] = res
            elif kind == "recall":
                recall_map[keyref] = res
            elif kind == "lit":
                lit_map[keyref] = res

    out: Dict[Pair, dict] = {}
    for pt, name, event in pairs:
        out[(name, event)] = {
            "label_evidence": label_map.get(name, {"available": False}) if pt != "device" else {"available": False, "source": "n/a_device"},
            "recall": recall_map.get((pt, name), {"available": False}),
            "literature": lit_map.get((name, event), {"available": False}),
            "device_classification": class_map.get(name, {"available": False}) if pt == "device" else {"available": False},
        }
    return out
