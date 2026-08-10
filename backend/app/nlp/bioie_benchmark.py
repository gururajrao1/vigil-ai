"""Evaluation adapters for BioIE corpora (PubTator / BC5CDR / NCBI Disease).

Offline precision / recall / F1 against gold entity spans. Corpora are loaded
from local JSON files when present; otherwise a tiny embedded fixture is used
so CI and demos never require network downloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


@dataclass
class Span:
    text: str
    start: int
    end: int
    type: str = "Disease"  # Chemical | Disease

    def key(self) -> Tuple[str, str]:
        return (self.type.lower(), self.text.strip().lower())


# Minimal BC5CDR-style fixture (chemical + disease mentions)
_EMBEDDED_FIXTURE: List[dict] = [
    {
        "id": "bc5cdr_demo_1",
        "text": "Patient developed severe nausea and headache after taking isotretinoin.",
        "entities": [
            {"text": "nausea", "start": 27, "end": 33, "type": "Disease"},
            {"text": "headache", "start": 38, "end": 46, "type": "Disease"},
            {"text": "isotretinoin", "start": 59, "end": 71, "type": "Chemical"},
        ],
    },
    {
        "id": "ncbi_demo_1",
        "text": "Lithium toxicity presenting with tremor and confusion.",
        "entities": [
            {"text": "Lithium toxicity", "start": 0, "end": 16, "type": "Disease"},
            {"text": "tremor", "start": 33, "end": 39, "type": "Disease"},
            {"text": "confusion", "start": 44, "end": 53, "type": "Disease"},
            {"text": "Lithium", "start": 0, "end": 7, "type": "Chemical"},
        ],
    },
    {
        "id": "bc5cdr_demo_2",
        "text": "Ibuprofen caused abdominal pain; patient denies chest pain.",
        "entities": [
            {"text": "Ibuprofen", "start": 0, "end": 9, "type": "Chemical"},
            {"text": "abdominal pain", "start": 17, "end": 31, "type": "Disease"},
            {"text": "chest pain", "start": 48, "end": 58, "type": "Disease"},
        ],
    },
    {
        "id": "pubtator_demo_1",
        "text": "Metformin and empagliflozin co-therapy; lactic acidosis was rare.",
        "entities": [
            {"text": "Metformin", "start": 0, "end": 9, "type": "Chemical"},
            {"text": "empagliflozin", "start": 14, "end": 27, "type": "Chemical"},
            {"text": "lactic acidosis", "start": 40, "end": 55, "type": "Disease"},
        ],
    },
]


def load_corpus(path: Optional[str] = None) -> List[dict]:
    if path:
        import json
        from pathlib import Path

        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else data.get("documents") or []
    return list(_EMBEDDED_FIXTURE)


def _predict_spans(text: str) -> List[Span]:
    from .entities import extract_entities

    ents = extract_entities(text, use_transformer=False)
    spans: List[Span] = []
    for d in ents.get("drugs") or []:
        spans.append(Span(
            text=d.get("text") or d.get("normalized") or "",
            start=int(d.get("start") or 0),
            end=int(d.get("end") or 0),
            type="Chemical",
        ))
    for s in ents.get("symptoms") or []:
        spans.append(Span(
            text=s.get("text") or s.get("normalized") or "",
            start=int(s.get("start") or 0),
            end=int(s.get("end") or 0),
            type="Disease",
        ))
    for c in ents.get("conditions") or []:
        spans.append(Span(
            text=c.get("text") or c.get("normalized") or "",
            start=int(c.get("start") or 0),
            end=int(c.get("end") or 0),
            type="Disease",
        ))
    return [s for s in spans if s.text]


def _prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def evaluate_corpus(
    *,
    corpus: str = "bc5cdr",
    path: Optional[str] = None,
    match: str = "text",  # text | exact_span
) -> Dict[str, Any]:
    """Benchmark VigilAI entity extraction vs gold BioIE annotations."""
    docs = load_corpus(path)
    tp = fp = fn = 0
    per_doc = []
    for doc in docs:
        text = doc.get("text") or ""
        gold = {
            Span(
                text=e["text"],
                start=int(e.get("start") or 0),
                end=int(e.get("end") or 0),
                type=e.get("type") or "Disease",
            ).key()
            for e in (doc.get("entities") or [])
        }
        pred_spans = _predict_spans(text)
        if match == "exact_span":
            pred = {(s.type.lower(), s.text.lower(), s.start, s.end) for s in pred_spans}
            gold_x = {
                (
                    (e.get("type") or "Disease").lower(),
                    e["text"].lower(),
                    int(e.get("start") or 0),
                    int(e.get("end") or 0),
                )
                for e in (doc.get("entities") or [])
            }
            d_tp = len(pred & gold_x)
            d_fp = len(pred - gold_x)
            d_fn = len(gold_x - pred)
        else:
            pred = {s.key() for s in pred_spans}
            d_tp = len(pred & gold)
            d_fp = len(pred - gold)
            d_fn = len(gold - pred)
        tp += d_tp
        fp += d_fp
        fn += d_fn
        per_doc.append({"id": doc.get("id"), **_prf(d_tp, d_fp, d_fn)})

    return {
        "corpus": corpus,
        "n_documents": len(docs),
        "match": match,
        "micro": _prf(tp, fp, fn),
        "per_document": per_doc,
        "note": (
            "Embedded fixture used when no local corpus path is provided. "
            "Compatible with BC5CDR / NCBI Disease JSON exports; PubTator "
            "Central can be converted offline to the same schema."
        ),
        "disclaimer": "Prototype BioIE eval adapter — not a published leaderboard run.",
    }
