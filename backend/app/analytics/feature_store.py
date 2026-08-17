"""Feature Store — Product–Event–Cohort matrix (X) for VigilAI ML.

Aggregates OMOP staging + Signal DMA metrics + demographic/comorbidity cues
into one structured row per (product, event, cohort) vector.

Offline-first.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import ProcessedPost, RawPost, Signal
from .disproportionality import compute_signals
from .knowledge_graph import build_graph
from .risk_features import (
    age_bracket,
    entities_from_processed,
    extract_comorbidities,
    parse_age_years,
    parse_sex,
    row_from_post,
)

logger = logging.getLogger("vigilai.feature_store")

_REGION_BUCKETS = ("NORTH_AMERICA", "EUROPE", "ASIA_PACIFIC", "GLOBAL")

_NA = {"us", "usa", "united states", "canada", "mexico", "north america"}
_EU = {"uk", "united kingdom", "germany", "france", "spain", "italy", "europe", "eu"}
_APAC = {"india", "china", "japan", "australia", "singapore", "asia", "apac"}

_RENAL = {"renal failure", "chronic kidney disease", "kidney disease"}
_WOUND = {
    "diabetic foot", "diabetic foot ulcer", "chronic wound", "pressure ulcer",
    "necrosis", "tissue necrosis", "skin erosion", "ulcer",
}
_CV = {"heart failure", "hypertension"}


def _region_bucket(region: Optional[str], country: Optional[str] = None) -> str:
    blob = f"{region or ''} {country or ''}".strip().lower()
    if any(t in blob for t in _NA):
        return "NORTH_AMERICA"
    if any(t in blob for t in _EU):
        return "EUROPE"
    if any(t in blob for t in _APAC):
        return "ASIA_PACIFIC"
    return "GLOBAL"


def _cohort_key(age_br: str, sex: str, region: str) -> str:
    return f"{age_br}|{sex or 'U'}|{region}"


def _one_hot_age(age_br: str) -> Dict[str, int]:
    return {
        "age_pediatric": 1 if age_br == "PEDIATRIC" else 0,
        "age_adult": 1 if age_br == "ADULT" else 0,
        "age_geriatric": 1 if age_br == "GERIATRIC" else 0,
        "age_unknown": 1 if age_br in ("UNKNOWN", "", None) else 0,
    }


def _one_hot_region(region: str) -> Dict[str, int]:
    return {f"region_{r.lower()}": 1 if region == r else 0 for r in _REGION_BUCKETS}


def _build_case_rows(
    db: Session,
    project_id: Optional[int],
    *,
    limit: int = 4000,
    product: Optional[str] = None,
    event: Optional[str] = None,
) -> List[dict]:
    """Build AE case rows. Capped so Render/Vercel gateways do not 504 on large corpora."""
    q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
        .order_by(ProcessedPost.id.desc())
    )
    if project_id is not None:
        q = q.filter(RawPost.project_id == project_id)
    # Prefer recent AE posts; hard cap keeps matrix under gateway timeout.
    cap = max(200, min(int(limit or 4000), 8000))
    q = q.limit(cap)
    rows = []
    prod_l = (product or "").strip().lower()
    event_l = (event or "").strip().lower()
    for processed, raw in q.all():
        ents = entities_from_processed(processed.entities_json)
        drugs = []
        for d in ents.get("drugs") or []:
            name = (d.get("normalized") or d.get("generic") or d.get("text") or "").strip().lower()
            if name:
                drugs.append(name)
        events = []
        for s in ents.get("symptoms") or []:
            ev = (s.get("pt") or s.get("normalized") or s.get("text") or "").strip().lower()
            if ev:
                events.append(ev)
        if not drugs or not events:
            continue
        if prod_l and not any(prod_l in d for d in drugs):
            continue
        if event_l and not any(event_l in e for e in events):
            continue
        text = f"{raw.title or ''} {raw.body or ''}"
        row = row_from_post(
            text=text,
            drugs=drugs,
            events=events,
            entities=ents,
            region=raw.region,
            product_type=raw.product_type or "drug",
        )
        row["drugs"] = drugs
        row["country"] = raw.country
        row["region_bucket"] = _region_bucket(raw.region, raw.country)
        row["age_bracket"] = row.get("age_bracket") or age_bracket(parse_age_years(text))
        row["sex"] = row.get("sex") or parse_sex(text) or "U"
        comorb, _ = extract_comorbidities(text, ents)
        row["comorbidities"] = comorb
        rows.append(row)
    return rows


def _signal_metrics(db: Session, project_id: Optional[int]) -> Dict[Tuple[str, str], dict]:
    """Pull PRR/ROR/χ²/EB05/IC025 from persisted Signal rows, else recompute."""
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    out: Dict[Tuple[str, str], dict] = {}
    for s in q.all():
        key = ((s.drug or "").lower(), (s.meddra_pt or s.symptom or "").lower())
        out[key] = {
            "prr_score": float(s.prr or 0.0),
            "ror_score": float(s.ror or 0.0),
            "chi_square": float(s.chi_square or 0.0),
            "eb05_score": float(getattr(s, "eb05", None) or 0.0),
            "ic025_score": float(getattr(s, "ic025", None) or 0.0),
            "ebgm": float(getattr(s, "ebgm", None) or 0.0),
            "ic": float(getattr(s, "ic", None) or 0.0),
            "strength": s.strength,
            "post_count": int(s.post_count or 0),
            "signal_id": s.id,
        }
    if out:
        return out

    # Fallback: recompute from AE posts
    reports: List[Tuple[str, str]] = []
    for r in _build_case_rows(db, project_id):
        for d in r.get("drugs") or [r.get("product")]:
            for e in r.get("events") or []:
                if d and e:
                    reports.append((str(d).lower(), str(e).lower()))
    for s in compute_signals(reports):
        key = (s["drug"].lower(), s["symptom"].lower())
        out[key] = {
            "prr_score": float(s.get("prr") or 0.0),
            "ror_score": float(s.get("ror") or 0.0),
            "chi_square": float(s.get("chi_square") or 0.0),
            "eb05_score": float(s.get("eb05") or 0.0),
            "ic025_score": float(s.get("ic025") or 0.0),
            "ebgm": float(s.get("ebgm") or 0.0),
            "ic": float(s.get("ic") or 0.0),
            "strength": s.get("strength"),
            "post_count": int(s.get("post_count") or 0),
            "signal_id": None,
        }
    return out


def _centrality_map(metrics: Dict[Tuple[str, str], dict]) -> Dict[str, float]:
    signals = [
        {
            "drug": d,
            "symptom": e,
            "prr": m.get("prr_score"),
            "strength": m.get("strength") or "WEAK",
            "post_count": m.get("post_count") or 1,
        }
        for (d, e), m in metrics.items()
    ]
    g = build_graph(signals)
    cent = {n["id"]: float(n.get("centrality") or 0.0) for n in g.get("nodes") or []}
    return cent


def build_feature_matrix(
    db: Session,
    *,
    project_id: Optional[int] = None,
    product: Optional[str] = None,
    event: Optional[str] = None,
    min_n: int = 1,
    include_gate_traces: bool = False,
    sample_text_limit: int = 0,
    case_limit: int = 4000,
) -> dict:
    """Build Product–Event–Cohort feature matrix X.

    Each row is a unique (product, event, age_bracket, sex, region) vector.
    """
    cases = _build_case_rows(
        db, project_id, limit=case_limit, product=product, event=event,
    )
    metrics = _signal_metrics(db, project_id)
    # Skip expensive graph pass when matrix is already large / unfiltered.
    centrality = _centrality_map(metrics) if len(metrics) <= 2500 else {}

    # Aggregate cases into cohort buckets
    buckets: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for r in cases:
        prods = r.get("drugs") or ([r.get("product")] if r.get("product") else [])
        evs = r.get("events") or []
        age_br = r.get("age_bracket") or "UNKNOWN"
        sex = (r.get("sex") or "U")[:1].upper()
        region = r.get("region_bucket") or "GLOBAL"
        for p in prods:
            for e in evs:
                if not p or not e:
                    continue
                if product and product.lower() not in str(p).lower():
                    continue
                if event and event.lower() not in str(e).lower():
                    continue
                key = (str(p).lower(), str(e).lower(), _cohort_key(age_br, sex, region))
                buckets[key].append(r)

    rows: List[dict] = []
    for (prod, ev, cohort), members in buckets.items():
        n = len(members)
        if n < min_n:
            continue
        age_br, sex, region = cohort.split("|", 2)
        comorb_all = []
        concomitant = 0
        for m in members:
            comorb_all.extend(m.get("comorbidities") or [])
            concomitant += len(m.get("concomitant_meds") or m.get("drugs") or []) - 1
        comorb_set = {c.lower() for c in comorb_all}
        dma = metrics.get((prod, ev), {})
        drug_node = f"drug::{prod}"
        event_node = f"symptom::{ev}"
        gnn = max(
            centrality.get(drug_node, 0.0),
            centrality.get(event_node, 0.0),
        )
        vector = {
            "product": prod,
            "event": ev,
            "cohort": cohort,
            "n_cases": n,
            # Statistical baseline
            "prr_score": dma.get("prr_score", 0.0),
            "ror_score": dma.get("ror_score", 0.0),
            "chi_square": dma.get("chi_square", 0.0),
            "eb05_score": dma.get("eb05_score", 0.0),
            "ic025_score": dma.get("ic025_score", 0.0),
            "strength": dma.get("strength"),
            "signal_id": dma.get("signal_id"),
            # Demographics
            **_one_hot_age(age_br),
            "sex_female": 1 if sex == "F" else 0,
            **_one_hot_region(region),
            # Clinical comorbidities & polypharmacy
            "has_renal_impairment": 1 if comorb_set & _RENAL else 0,
            "has_chronic_wound": 1 if comorb_set & _WOUND else 0,
            "has_cardiovascular_disease": 1 if comorb_set & _CV else 0,
            "concomitant_drug_count": max(0, concomitant // max(n, 1)),
            # Graph topology
            "gnn_degree_centrality": round(gnn, 4),
        }
        rows.append(vector)

    rows.sort(key=lambda r: (-(r.get("prr_score") or 0), -r["n_cases"]))

    gate_traces = None
    if include_gate_traces and sample_text_limit > 0:
        from ..nlp.four_gate_engine import run_four_gates

        gate_traces = []
        q = (
            db.query(ProcessedPost, RawPost)
            .join(RawPost, ProcessedPost.raw_id == RawPost.id)
            .filter(ProcessedPost.ae_flag.is_(True))
            .limit(sample_text_limit)
        )
        for processed, raw in q.all():
            text = f"{raw.title or ''}\n{raw.body or ''}".strip()
            gate_traces.append({
                "raw_id": raw.id,
                "trace": run_four_gates(text, use_transformer=False),
            })

    feature_names = [
        "prr_score", "ror_score", "chi_square", "eb05_score", "ic025_score",
        "age_pediatric", "age_adult", "age_geriatric", "age_unknown",
        "sex_female",
        "region_north_america", "region_europe", "region_asia_pacific", "region_global",
        "has_renal_impairment", "has_chronic_wound", "has_cardiovascular_disease",
        "concomitant_drug_count", "gnn_degree_centrality",
    ]

    return {
        "n_rows": len(rows),
        "n_source_ae_posts": len(cases),
        "feature_names": feature_names,
        "matrix": rows,
        "X": [[r.get(f, 0) for f in feature_names] for r in rows],
        "row_keys": [
            {"product": r["product"], "event": r["event"], "cohort": r["cohort"], "n_cases": r["n_cases"]}
            for r in rows
        ],
        "gate_traces": gate_traces,
        "ontology_stack": [
            "RxNorm/ATC (drug_concept_id)",
            "MedDRA-style PT (condition_concept_id)",
            "GMDN (device_concept_id)",
            "OMOP CDM v5.4 staging (person/exposure/condition)",
        ],
        "disclaimer": (
            "Feature matrix over social/ICSR-derived OMOP staging. "
            "Open MedDRA/SNOMED/UMLS-style coding."
        ),
    }


def get_normalized_feature_matrix(
    db: Session,
    *,
    product_id: Optional[str] = None,
    target_ae_pt: Optional[str] = None,
    project_id: Optional[int] = None,
    include_explainability: bool = True,
) -> dict:
    """FastMCP / API entry — feature vector X + optional 4-gate traces."""
    # Unfiltered scans are capped tighter so Vercel→Render rewrites stay under gateway limits.
    filtered = bool((product_id or "").strip() or (target_ae_pt or "").strip())
    out = build_feature_matrix(
        db,
        project_id=project_id,
        product=product_id,
        event=target_ae_pt,
        include_gate_traces=include_explainability,
        sample_text_limit=3 if include_explainability else 0,
        case_limit=4000 if filtered else 1500,
    )
    # Attach a compact 4-gate explainability summary for the top product-event
    explain = None
    if include_explainability and out["matrix"]:
        top = out["matrix"][0]
        explain = {
            "focus_product": top["product"],
            "focus_event": top["event"],
            "cohort": top["cohort"],
            "feature_vector": {f: top.get(f) for f in out["feature_names"]},
            "gate_trace_samples": out.get("gate_traces"),
        }
    return {
        **out,
        "explainability": explain,
        "method": "product_event_cohort_feature_store_v1",
    }
