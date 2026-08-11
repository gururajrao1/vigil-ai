"""Disproportionality computed on the MedDRA hierarchy, not just raw event labels.

Two passes over the same corpus of (product, event) reports:

1. **PT level** — the conventional 2x2 disproportionality already used by Detect,
   but keyed on the MedDRA-surrogate Preferred Term so synonym spellings pool.
2. **SOC level** — member PTs rolled up into their System Organ Class before the
   2x2 is built. A product can look unremarkable on every individual PT and still
   be disproportionate across the organ class ("signal strengthening" in the
   Hauben/Trontell sense), which is what ``soc_alerts`` surfaces.

The statistics themselves are the existing PRR/ROR/chi-square/EBGM/IC helpers in
``analytics.disproportionality`` — this module only changes what gets counted, so
the SOC layer is an overlay on Detect, never a replacement for it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import Signal
from ..nlp.ontology_engine import meddra_mapper
from ..nlp.ontology_engine.models import ONTOLOGY_VERSION, SURROGATE_DISCLAIMER
from .disproportionality import compute_signals

# Guard so a large workspace cannot expand into an unbounded pair list.
_MAX_EXPANDED_PAIRS = 200_000

# SOC-level roll-up alert gates. A SOC clears "strengthening" when the organ-class
# 2x2 is a signal of disproportionate reporting while no single member PT is.
_SPARSE_PT_COUNT = 3


def _chain_for(symptom: str, stored_pt: Optional[str], stored_soc: Optional[str]) -> Dict[str, Optional[str]]:
    """Resolve PT/HLT/HLGT/SOC for one signal, preferring stored coding."""
    chain = meddra_mapper.map_event(stored_pt or symptom)
    pt = chain.pt or stored_pt or (symptom or "").strip().title()
    soc = chain.soc if chain.matched else (stored_soc or chain.soc)
    return {
        "pt": pt,
        "hlt": chain.hlt,
        "hlgt": chain.hlgt,
        "soc": soc,
        "soc_code": chain.soc_code,
        "matched": chain.matched,
    }


def _expand(pairs: Counter) -> List[Tuple[str, str]]:
    """Weighted pair counts → the report list the 2x2 helpers expect."""
    total = sum(pairs.values())
    scale = 1.0
    if total > _MAX_EXPANDED_PAIRS:
        scale = _MAX_EXPANDED_PAIRS / float(total)
    out: List[Tuple[str, str]] = []
    for pair, count in pairs.items():
        weight = max(1, int(round(count * scale)))
        out.extend([pair] * weight)
    return out


def compute_ontological_disproportionality(
    db: Session,
    *,
    project_id: Optional[int] = None,
    product: Optional[str] = None,
    min_count: int = 1,
    top_n: int = 100,
) -> dict:
    """PT-level and SOC-level disproportionality plus organ-class alerts."""
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    if product:
        q = q.filter(Signal.drug == product.strip().lower())
    rows = q.all()

    pt_pairs: Counter = Counter()
    soc_pairs: Counter = Counter()
    hierarchy: Dict[str, Dict[str, Optional[str]]] = {}
    members: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    unmatched_pts: set[str] = set()

    for sig in rows:
        count = int(sig.post_count or 0)
        if count <= 0:
            continue
        drug = (sig.drug or "").strip().lower()
        if not drug:
            continue
        chain = _chain_for(sig.symptom or "", sig.meddra_pt, sig.meddra_soc)
        pt = chain["pt"] or (sig.symptom or "").strip().title()
        soc = chain["soc"] or "General disorders and administration site conditions"
        hierarchy[pt] = chain
        if not chain["matched"]:
            unmatched_pts.add(pt)
        pt_pairs[(drug, pt)] += count
        soc_pairs[(drug, soc)] += count
        members[(drug, soc)][pt] += count

    if not pt_pairs:
        return {
            "pt_table": [],
            "soc_table": [],
            "soc_alerts": [],
            "totals": {"signals": len(rows), "pt_pairs": 0, "soc_pairs": 0, "reports": 0},
            "verdict": "No AE-coded signals in scope — run Ingest + Detect first.",
            "how_to_read": _HOW_TO_READ,
            "ontology_version": ONTOLOGY_VERSION,
            "disclaimer": SURROGATE_DISCLAIMER,
        }

    pt_stats = compute_signals(_expand(pt_pairs))
    soc_stats = compute_signals(_expand(soc_pairs))

    pt_by_key = {(r["drug"], r["symptom"]): r for r in pt_stats}
    pt_table = []
    for row in pt_stats:
        key = (row["drug"], row["symptom"])
        if pt_pairs.get(key, 0) < min_count:
            continue
        chain = hierarchy.get(row["symptom"], {})
        pt_table.append({
            **row,
            "product": row["drug"],
            "pt": row["symptom"],
            "observed_reports": pt_pairs.get(key, row["post_count"]),
            "hlt": chain.get("hlt"),
            "hlgt": chain.get("hlgt"),
            "soc": chain.get("soc"),
            "soc_code": chain.get("soc_code"),
            "hierarchy_matched": bool(chain.get("matched")),
        })

    soc_table = []
    soc_alerts = []
    for row in soc_stats:
        key = (row["drug"], row["symptom"])
        member_counts = members.get(key, Counter())
        member_rows = [
            {
                "pt": pt,
                "reports": count,
                "sdr_flag": bool(pt_by_key.get((row["drug"], pt), {}).get("sdr_flag")),
                "prr": pt_by_key.get((row["drug"], pt), {}).get("prr"),
                "eb05": pt_by_key.get((row["drug"], pt), {}).get("eb05"),
            }
            for pt, count in member_counts.most_common()
        ]
        entry = {
            **row,
            "product": row["drug"],
            "soc": row["symptom"],
            "observed_reports": soc_pairs.get(key, row["post_count"]),
            "n_member_pts": len(member_rows),
            "members": member_rows[:12],
        }
        soc_table.append(entry)

        max_pt_reports = max((m["reports"] for m in member_rows), default=0)
        any_pt_sdr = any(m["sdr_flag"] for m in member_rows)
        if row["sdr_flag"] and not any_pt_sdr and max_pt_reports < _SPARSE_PT_COUNT:
            soc_alerts.append({
                "product": row["drug"],
                "soc": row["symptom"],
                "reports": entry["observed_reports"],
                "n_member_pts": len(member_rows),
                "prr": row["prr"],
                "prr_ci_low": row["prr_ci_low"],
                "chi_square": row["chi_square"],
                "eb05": row["eb05"],
                "ic025": row["ic025"],
                "strength": row["strength"],
                "member_pts": [m["pt"] for m in member_rows[:8]],
                "reason": (
                    f"{row['symptom']} clears SDR gates at organ-class level "
                    f"({len(member_rows)} member PTs, largest single PT has "
                    f"{max_pt_reports} report(s)) — a diffuse class signal no single "
                    "PT would raise."
                ),
                "recommended_action": (
                    "Review the member PTs together as one organ-class hypothesis "
                    "before dismissing them as sparse noise."
                ),
            })

    pt_table = pt_table[:top_n]
    soc_table = soc_table[:top_n]

    if soc_alerts:
        verdict = (
            f"{len(soc_alerts)} organ-class alert(s): disproportionality appears at SOC "
            "level while member Preferred Terms stay below single-PT thresholds."
        )
    elif any(r["sdr_flag"] for r in pt_table):
        verdict = (
            "PT-level signals are carrying the disproportionality; no SOC roll-up "
            "adds a hypothesis the PT view misses."
        )
    else:
        verdict = (
            "No disproportionate reporting at PT or SOC level in this scope — expected "
            "when the corpus is small or evenly spread across products."
        )

    return {
        "pt_table": pt_table,
        "soc_table": soc_table,
        "soc_alerts": soc_alerts,
        "totals": {
            "signals": len(rows),
            "pt_pairs": len(pt_pairs),
            "soc_pairs": len(soc_pairs),
            "reports": sum(pt_pairs.values()),
            "unmatched_pts": len(unmatched_pts),
        },
        "verdict": verdict,
        "how_to_read": _HOW_TO_READ,
        "ontology_version": ONTOLOGY_VERSION,
        "disclaimer": SURROGATE_DISCLAIMER,
    }


_HOW_TO_READ = (
    "PT rows are the familiar Detect statistics keyed on the MedDRA-surrogate "
    "Preferred Term. SOC rows pool every member PT for that product into one 2x2 "
    "before computing PRR/ROR/EBGM/IC, so an organ-class pattern spread thin across "
    "many rare terms becomes visible. An entry in soc_alerts means the class cleared "
    "SDR gates while no member PT did — investigate, do not auto-escalate."
)
