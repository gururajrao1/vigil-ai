"""Concurrent multi-source evidence enrichment for signals.

Given the detected (drug/device, event) pairs, gather — in parallel, cached, with
short timeouts so recompute never hangs — real keyless evidence:

  * DailyMed label match          (per drug)
  * openFDA recall / enforcement  (per product)
  * openFDA device classification (per device)
  * PubMed literature             (per pair)

Per-product lookups are deduped so we issue far fewer network calls than there are
signals. Everything degrades to a deterministic offline result.

Signal Detail must NEVER block on enrichment — use ``enrich_signal_background``
from a FastAPI BackgroundTask so GET /signals/{id} returns DB rows immediately.
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

from ..config import settings
from .dailymed import query_dailymed
from .device_class import query_device_classification
from .pubmed import query_pubmed
from .recalls import query_recalls

Pair = Tuple[str, str]
logger = logging.getLogger("vigilai.enrich")

_ENRICH_LOCK = threading.Lock()
_ENRICHING: set[int] = set()
_PENDING_MARKER = {"available": False, "source": "enrich_pending"}


def needs_network_enrichment(literature_json: Optional[str]) -> bool:
    """True when this signal has never completed (or never started) enrichment."""
    if literature_json in (None, "", "{}"):
        return True
    try:
        lit = json.loads(literature_json)
    except Exception:
        return True
    if not isinstance(lit, dict) or not lit:
        return True
    src = (lit.get("source") or "").strip()
    # Still waiting on a prior background job — don't pile on; job owns the write.
    if src == "enrich_pending":
        return False
    return False


def mark_enrich_pending(literature_json: Optional[str] = None) -> str:
    return json.dumps(_PENDING_MARKER)


def enrich_one(product_type: str, name: str, event: str, timeout: float = 2.5) -> dict:
    """Enrich a SINGLE (product, event) pair — used lazily / in background.

    At most 4 outbound calls (cached). Every source degrades to a deterministic fallback.
    Default timeout kept short so free-tier APIs (Render) don't stall workers.
    """
    if not settings.use_evidence_enrichment:
        return {
            "label_evidence": {"available": False, "source": "disabled"},
            "recall": {"available": False, "source": "disabled"},
            "literature": {"available": False, "source": "disabled"},
            "device_classification": {"available": False, "source": "disabled"},
        }
    is_device = (product_type or "drug") == "device"
    out: dict = {
        "label_evidence": {"available": False, "source": "dailymed_offline"},
        "recall": {"available": False, "source": "recall_offline"},
        "literature": {"available": False, "source": "pubmed_offline"},
        "device_classification": {"available": False, "source": "device_class_offline"},
    }
    ex = ThreadPoolExecutor(max_workers=4)
    try:
        futs = {
            ex.submit(query_recalls, product_type, name, timeout): "recall",
            ex.submit(query_pubmed, name, event, timeout): "literature",
        }
        if not is_device:
            futs[ex.submit(query_dailymed, name, timeout)] = "label_evidence"
        else:
            futs[ex.submit(query_device_classification, name, timeout)] = "device_classification"

        # Wait in parallel — sequential .result() was stacking timeouts (~8s+)
        # Do NOT use `with ThreadPoolExecutor` — its __exit__ waits for hung HTTP threads.
        deadline = timeout + 1.0
        try:
            for fut in as_completed(futs, timeout=deadline):
                key = futs[fut]
                try:
                    res = fut.result(timeout=0)
                    if res:
                        out[key] = res
                except Exception:
                    pass
        except TimeoutError:
            pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return out


def enrich_signal_background(signal_id: int) -> None:
    """Persist multi-source evidence for one signal without blocking the request path.

    Safe to call concurrently — duplicate IDs are skipped while a run is in flight.
    Always writes a non-pending literature_json so later GETs stay fast.
    """
    with _ENRICH_LOCK:
        if signal_id in _ENRICHING:
            return
        _ENRICHING.add(signal_id)
    try:
        from ..database import SessionLocal
        from ..models import Signal

        db = SessionLocal()
        try:
            sig = db.get(Signal, signal_id)
            if not sig:
                return
            ev = enrich_one(
                sig.product_type or "drug",
                sig.drug or "",
                sig.symptom or "",
                timeout=2.5,
            )
            sig.label_evidence_json = json.dumps(ev.get("label_evidence") or {})
            sig.recall_json = json.dumps(ev.get("recall") or {})
            lit = ev.get("literature") or {"available": False, "source": "pubmed_offline"}
            if not lit.get("source") or lit.get("source") == "enrich_pending":
                lit = {**lit, "source": lit.get("source") or "pubmed_offline"}
            sig.literature_json = json.dumps(lit)
            sig.device_class_json = json.dumps(ev.get("device_classification") or {})

            if (sig.product_type or "drug") == "device" and sig.drug:
                try:
                    from ..ingestion.sources import query_eudamed
                    eudamed = query_eudamed(sig.drug, timeout=4.0)
                    if eudamed.get("available"):
                        existing = json.loads(sig.device_class_json or "{}")
                        existing["eudamed"] = eudamed
                        sig.device_class_json = json.dumps(existing)
                except Exception:
                    logger.debug("eudamed enrich failed for signal %s", signal_id, exc_info=True)

            db.commit()
        except Exception:
            logger.exception("background enrich failed for signal %s", signal_id)
            try:
                db.rollback()
                sig = db.get(Signal, signal_id)
                if sig:
                    # Persist offline stubs so GET never re-blocks on this id
                    sig.literature_json = json.dumps(
                        {"available": False, "source": "pubmed_offline"}
                    )
                    if not sig.label_evidence_json:
                        sig.label_evidence_json = json.dumps(
                            {"available": False, "source": "dailymed_offline"}
                        )
                    if not sig.recall_json:
                        sig.recall_json = json.dumps(
                            {"available": False, "source": "recall_offline"}
                        )
                    if not sig.device_class_json:
                        sig.device_class_json = json.dumps(
                            {"available": False, "source": "device_class_offline"}
                        )
                    db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()
    finally:
        with _ENRICH_LOCK:
            _ENRICHING.discard(signal_id)


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
