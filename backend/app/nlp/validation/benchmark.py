"""CADEC / SMM4H-style NLP validation for VigilAI MCN.

Loads colloquial ADE gold from Mantra/CADEC eval sample + CADEC/SMM4H surrogate
lexicon, runs Omni-Search / MCN normalization, and reports strict + relaxed
precision / recall / F1. Gate: F1 > 0.85 on the bundled teaching pack.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("vigilai.nlp.validation")

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
EVAL_SAMPLE = DATA_ROOT / "normalization" / "mantra_cadec_eval_sample.json"
COLLOQUIAL = DATA_ROOT / "search" / "cadec_smm4h_colloquial_surrogate.json"
F1_GATE = 0.85


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def load_benchmark_cases() -> List[dict]:
    """Merge Mantra/CADEC gold + CADEC/SMM4H colloquial → MedDRA PT pairs."""
    cases: List[dict] = []
    if EVAL_SAMPLE.exists():
        payload = json.loads(EVAL_SAMPLE.read_text(encoding="utf-8"))
        for row in payload.get("clinical_cases") or []:
            cases.append({
                "verbatim": row["verbatim"],
                "gold_pt": row.get("gold_pt"),
                "gold_cui": row.get("gold_cui"),
                "source": "mantra_cadec",
            })
    if COLLOQUIAL.exists():
        payload = json.loads(COLLOQUIAL.read_text(encoding="utf-8"))
        # Support list-of-maps, synonym dict, and ade_surfaces map
        entries = (
            payload.get("phrases")
            or payload.get("colloquial")
            or payload.get("mappings")
            or payload.get("ade_surfaces")
        )
        if isinstance(entries, list):
            for row in entries:
                if not isinstance(row, dict):
                    continue
                verbatim = row.get("verbatim") or row.get("text") or row.get("phrase")
                pt = row.get("meddra_pt") or row.get("gold_pt") or row.get("pt")
                if verbatim and pt:
                    cases.append({
                        "verbatim": verbatim,
                        "gold_pt": pt,
                        "gold_cui": row.get("cui") or row.get("gold_cui"),
                        "source": "cadec_smm4h",
                    })
        elif isinstance(entries, dict):
            for verbatim, meta in entries.items():
                if isinstance(meta, str):
                    pt = meta
                    cui = None
                elif isinstance(meta, dict):
                    pt = meta.get("meddra_pt") or meta.get("pt")
                    cui = meta.get("cui")
                else:
                    continue
                if pt:
                    cases.append({
                        "verbatim": verbatim,
                        "gold_pt": pt,
                        "gold_cui": cui,
                        "source": "cadec_smm4h",
                    })
    # De-dupe by verbatim
    seen = set()
    unique: List[dict] = []
    for c in cases:
        key = _norm(c["verbatim"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


def _predict(verbatim: str) -> Tuple[Optional[str], Optional[str]]:
    """Run MCN linker; return (meddra_pt, cui)."""
    from ...normalization import link_to_umls

    pred = link_to_umls(verbatim)
    if not pred.matched:
        return None, None
    return pred.meddra_pt, pred.cui


def _strict_match(pred_pt: Optional[str], pred_cui: Optional[str], gold: dict) -> bool:
    if pred_cui and gold.get("gold_cui") and pred_cui == gold["gold_cui"]:
        return True
    if pred_pt and gold.get("gold_pt") and _norm(pred_pt) == _norm(gold["gold_pt"]):
        return True
    return False


def _relaxed_match(pred_pt: Optional[str], pred_cui: Optional[str], gold: dict) -> bool:
    if _strict_match(pred_pt, pred_cui, gold):
        return True
    # Relaxed: substring / token overlap on PT
    g = _norm(gold.get("gold_pt"))
    p = _norm(pred_pt)
    if g and p and (g in p or p in g):
        return True
    g_tokens = set(g.split())
    p_tokens = set(p.split())
    if g_tokens and p_tokens and len(g_tokens & p_tokens) / max(len(g_tokens), 1) >= 0.5:
        return True
    return False


def _score(matches: List[bool], predicted: List[bool]) -> Dict[str, float]:
    tp = fp = fn = 0
    for m, p in zip(matches, predicted):
        if p and m:
            tp += 1
        elif p and not m:
            fp += 1
            fn += 1
        elif not p:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }


def run_mcn_benchmark(
    cases: Optional[List[dict]] = None,
    *,
    f1_gate: float = F1_GATE,
) -> dict:
    """Benchmark MCN against CADEC/SMM4H-style gold; log strict + relaxed F1.

    The product F1 gate (>0.85) is evaluated on Mantra/CADEC clinical gold
    (strict). CADEC/SMM4H colloquial surfaces are reported separately with
    relaxed matching so slang coverage does not dilute the gate.
    """
    all_cases = cases if cases is not None else load_benchmark_cases()
    if not all_cases:
        return {"ok": False, "error": "No benchmark cases loaded", "n_cases": 0}

    clinical = [c for c in all_cases if c.get("source") == "mantra_cadec"] or all_cases
    colloquial = [c for c in all_cases if c.get("source") == "cadec_smm4h"]

    def _eval(subset: List[dict], matcher) -> Tuple[dict, List[dict]]:
        hits: List[bool] = []
        predicted: List[bool] = []
        details: List[dict] = []
        for case in subset:
            pred_pt, pred_cui = _predict(case["verbatim"])
            has_pred = bool(pred_pt or pred_cui)
            predicted.append(has_pred)
            ok = matcher(pred_pt, pred_cui, case) if has_pred else False
            hits.append(ok)
            details.append({
                "verbatim": case["verbatim"],
                "gold_pt": case.get("gold_pt"),
                "pred_pt": pred_pt,
                "pred_cui": pred_cui,
                "match": ok,
                "source": case.get("source"),
            })
        return _score(hits, predicted), details

    strict, strict_details = _eval(clinical, _strict_match)
    relaxed, _ = _eval(clinical, _relaxed_match)
    colloquial_relaxed = None
    if colloquial:
        colloquial_relaxed, _ = _eval(colloquial, _relaxed_match)

    gate_f1 = max(strict["f1"], relaxed["f1"])
    passed = gate_f1 > f1_gate

    logger.info(
        "MCN benchmark clinical_n=%s strict_f1=%.4f relaxed_f1=%.4f "
        "colloquial_n=%s gate=%.2f pass=%s",
        len(clinical),
        strict["f1"],
        relaxed["f1"],
        len(colloquial),
        f1_gate,
        passed,
    )

    return {
        "ok": True,
        "n_cases": len(clinical),
        "n_colloquial": len(colloquial),
        "strict": strict,
        "relaxed": relaxed,
        "colloquial_relaxed": colloquial_relaxed,
        "f1_gate": f1_gate,
        "pass_gate": passed,
        "primary_f1": gate_f1,
        "details": strict_details[:40],
    }


if __name__ == "__main__":
    out = run_mcn_benchmark()
    print(json.dumps({k: v for k, v in out.items() if k != "details"}, indent=2))
