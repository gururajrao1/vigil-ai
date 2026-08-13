"""Pregnancy / teratogen cohort mode with stratified disproportionality."""
from __future__ import annotations

import re
from typing import List, Set, Tuple

from .disproportionality import compute_signals

_PREGNANCY_CUES = re.compile(
    r"\b("
    r"pregnan(?:t|cy|cies)|trimester|gestation|prenatal|antenatal|"
    r"fetal|foetal|fetus|foetus|embryo|embryonic|"
    r"congenital|birth\s*defect|teratogen(?:ic|icity)?|"
    r"neonat(?:e|al)|newborn|lactation|breast.?feed|"
    r"miscarriage|stillbirth|iPledge|contraception\s+required|"
    r"in\s+utero|maternal\s+exposure|pregnancy\s+exposure"
    r")\b",
    re.I,
)

CONGENITAL_EVENTS: Set[str] = {
    "birth defect", "birth defects", "congenital anomaly", "congenital anomalies",
    "teratogenicity", "cleft palate", "cleft lip", "neural tube defect",
    "spina bifida", "cardiac malformation", "heart defect", "limb reduction",
    "hypospadias", "microcephaly", "fetal growth restriction",
    "intrauterine growth restriction", "stillbirth", "miscarriage",
    "spontaneous abortion", "neonatal death", "fetal death", "embryotoxicity",
    "developmental delay", "patent ductus arteriosus", "congenital malformation",
    "foetal damage", "congenital cardiac disorder", "neonatal renal impairment",
    "neonatal renal failure", "abortion spontaneous",
}


def is_pregnancy_text(text: str) -> bool:
    return bool(text and _PREGNANCY_CUES.search(text))


def is_congenital_event(event: str) -> bool:
    e = (event or "").lower().strip()
    if not e:
        return False
    if e in CONGENITAL_EVENTS:
        return True
    for c in CONGENITAL_EVENTS:
        if c in e or e in c:
            return True
    # Token cues
    return any(tok in e for tok in (
        "congenital", "teratogen", "cleft", "neural tube", "spina",
        "malformation", "birth defect", "stillbirth", "miscarriage",
        "foetal", "fetal", "abortion", "neonatal renal", "embryotox",
    ))


def filter_pregnancy_posts(posts: List[dict]) -> List[dict]:
    out = []
    for p in posts:
        text = p.get("text") or ""
        events = p.get("events") or []
        if is_pregnancy_text(text) or any(is_congenital_event(e) for e in events):
            out.append(p)
    return out


def pregnancy_demo_posts() -> List[dict]:
    """Offline pregnancy/teratogen demo ICSRs designed to pass 4-gate AE NLP.

    Bodies intentionally include lexicon drug + congenital/pregnancy event surfaces
    plus negative sentiment cues so ingest → ProcessedPost.ae_flag → Signal rows.
    """
    from datetime import datetime, timedelta

    base = datetime.utcnow() - timedelta(days=40)
    rows = [
        ("isotretinoin", "birth defect",
         "Horrible pregnancy exposure to isotretinoin despite iPLEDGE; congenital birth defect reported — terrified of fetal harm."),
        ("isotretinoin", "teratogenicity",
         "Pregnant patient wrongly stayed on isotretinoin — severe teratogenicity and fetal harm concern, devastated."),
        ("valproate", "neural tube defect",
         "Maternal valproate exposure in first trimester; tragic neural tube defect / spina bifida diagnosis."),
        ("valproate", "birth defect",
         "Pregnancy exposure to sodium valproate with serious congenital anomaly / birth defect — awful outcome."),
        ("topiramate", "cleft palate",
         "Antenatal topiramate exposure; infant born with cleft palate, family is devastated."),
        ("warfarin", "birth defect",
         "Fetal warfarin syndrome concern after pregnancy exposure; painful birth defect reported."),
        ("methotrexate", "miscarriage",
         "Methotrexate taken around conception; suffered miscarriage / spontaneous abortion — heartbreaking."),
        ("lisinopril", "neonatal renal impairment",
         "Pregnancy trimester exposure to lisinopril ACE inhibitor; neonatal renal impairment — critically ill newborn."),
        ("carbamazepine", "neural tube defect",
         "Prenatal carbamazepine exposure; neural tube defect under investigation — frightening pregnancy outcome."),
        ("lithium", "cardiac malformation",
         "Pregnancy exposure to lithium; serious cardiac malformation (Ebstein anomaly concern) — catastrophic fetal harm."),
    ]
    posts = []
    for i, (drug, reaction, body) in enumerate(rows):
        posts.append({
            "external_id": f"preg_demo:v2:{i+1}",
            "platform": "pregnancy_demo",
            "author": f"preg_demo:v2:{i+1}",
            "title": f"Pregnancy cohort: {drug} -> {reaction}",
            "body": body,
            "url": "",
            "posted_at": base + timedelta(days=i * 3),
            "region": "North America",
            "country": "US",
            "language": "en",
            "product_type": "drug",
        })
    return posts


def stratified_pregnancy_dma(posts: List[dict], *, min_count: int = 1) -> dict:
    cohort = filter_pregnancy_posts(posts)
    reports: List[Tuple[str, str]] = []
    for p in cohort:
        for d in p.get("drugs") or []:
            for e in p.get("events") or []:
                reports.append((d, e))

    signals = compute_signals(reports) if reports else []
    congenital, other = [], []
    for s in signals:
        if (s.get("post_count") or 0) < min_count:
            continue
        row = {**s, "pregnancy_cohort": True, "congenital_stratum": is_congenital_event(s["symptom"])}
        (congenital if row["congenital_stratum"] else other).append(row)

    empty = len(cohort) == 0
    return {
        "n_posts_total": len(posts),
        "n_pregnancy_posts": len(cohort),
        "n_reports": len(reports),
        "congenital_signals": congenital[:40],
        "other_pregnancy_signals": other[:40],
        "needs_demo_seed": empty or (len(congenital) == 0 and len(other) < 2),
        "verdict": (
            "No pregnancy-context posts in this project yet — load the pregnancy demo pack."
            if empty
            else (
                f"{len(congenital)} congenital-stratum signal(s) and {len(other)} other "
                f"pregnancy-context signal(s) in a cohort of {len(cohort)} posts."
            )
        ),
        "method": "Lexicon pregnancy cohort + stratified DMA (congenital anomaly PTs)",
        "registries_note": (
            "Point to pregnancy-exposure registries in /api/evidence/registry "
            "(surrogate links — not live VigiBase)."
        ),
        "disclaimer": (
            "Pregnancy cohort mode is a social/FAERS-text surrogate. "
            "Pregnancy-context view over social/ICSR-style text."
        ),
    }
