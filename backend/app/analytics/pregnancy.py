"""Pregnancy / teratogen cohort mode with stratified disproportionality.

Detects pregnancy-exposure narratives (lexicon + congenital-anomaly PT set) and
runs DMA restricted to that cohort — FAERS pregnancy-study style stratified analysis.

Offline lexicon; registry pointers remain surrogates in evidence/registry.py.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

from .disproportionality import compute_signals

# Exposure / pregnancy context cues
_PREGNANCY_CUES = re.compile(
    r"\b("
    r"pregnan(?:t|cy|cies)|trimester|gestation|prenatal|antenatal|"
    r"fetal|foetal|fetus|foetus|embryo|embryonic|"
    r"congenital|birth\s*defect|teratogen(?:ic|icity)?|"
    r"neonat(?:e|al)|newborn|lactation|breast.?feed|"
    r"miscarriage|stillbirth|iPledge|contraception\s+required"
    r")\b",
    re.I,
)

# Congenital anomaly / pregnancy outcome event surface forms (open MedDRA surrogate)
CONGENITAL_EVENTS: Set[str] = {
    "birth defect", "birth defects", "congenital anomaly", "congenital anomalies",
    "teratogenicity", "cleft palate", "cleft lip", "neural tube defect",
    "spina bifida", "cardiac malformation", "heart defect", "limb reduction",
    "hypospadias", "microcephaly", "fetal growth restriction",
    "intrauterine growth restriction", "stillbirth", "miscarriage",
    "spontaneous abortion", "neonatal death", "fetal death", "embryotoxicity",
    "developmental delay", "patent ductus arteriosus",
}


def is_pregnancy_text(text: str) -> bool:
    return bool(text and _PREGNANCY_CUES.search(text))


def is_congenital_event(event: str) -> bool:
    e = (event or "").lower().strip()
    if e in CONGENITAL_EVENTS:
        return True
    return any(c in e or e in c for c in CONGENITAL_EVENTS)


def filter_pregnancy_posts(posts: List[dict]) -> List[dict]:
    """Keep posts with pregnancy lexicon OR congenital anomaly events."""
    out = []
    for p in posts:
        text = p.get("text") or ""
        events = p.get("events") or []
        if is_pregnancy_text(text) or any(is_congenital_event(e) for e in events):
            out.append(p)
    return out


def stratified_pregnancy_dma(posts: List[dict], *, min_count: int = 1) -> dict:
    """Run DMA on pregnancy cohort; highlight congenital-anomaly strata."""
    cohort = filter_pregnancy_posts(posts)
    reports: List[Tuple[str, str]] = []
    for p in cohort:
        for d in p.get("drugs") or []:
            for e in p.get("events") or []:
                reports.append((d, e))

    signals = compute_signals(reports) if reports else []
    congenital = []
    other = []
    for s in signals:
        if (s.get("post_count") or 0) < min_count:
            continue
        row = {**s, "pregnancy_cohort": True, "congenital_stratum": is_congenital_event(s["symptom"])}
        if row["congenital_stratum"]:
            congenital.append(row)
        else:
            other.append(row)

    return {
        "n_posts_total": len(posts),
        "n_pregnancy_posts": len(cohort),
        "n_reports": len(reports),
        "congenital_signals": congenital[:40],
        "other_pregnancy_signals": other[:40],
        "method": "Lexicon pregnancy cohort + stratified DMA (congenital anomaly PTs)",
        "registries_note": (
            "Point to pregnancy-exposure registries in /api/evidence/registry "
            "(surrogate links — not live VigiBase)."
        ),
        "disclaimer": (
            "Pregnancy cohort mode is a social/FAERS-text surrogate. "
            "Not a pregnancy registry analysis; not for clinical use."
        ),
    }
