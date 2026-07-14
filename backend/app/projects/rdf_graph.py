"""Step 6 — in-memory rdflib graph, SPARQL filters, and KG story narration."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional, Set

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS
from sqlalchemy.orm import Session

from ..models import Alert, ProcessedPost, RawPost, Signal
from ..nlp.drug_norm import canonical_product
from ..nlp.text_normalize import canonical_event, dedupe_labels, normalize_label
from .kg_story import build_kg_story
from .stitch_enrich import enrich_graph

logger = logging.getLogger("vigilai.rdf_graph")

VIG = Namespace("http://vigilai.dev/ontology#")
REGION = Namespace("http://vigilai.dev/region#")

# Bump when materialization / normalization rules change (busts in-process cache).
_GRAPH_BUILD_VERSION = 5

_LOCK = threading.Lock()
_GRAPH_CACHE: Dict[int, Graph] = {}
_GRAPH_SIG: Dict[int, tuple] = {}
_FILTER_OPTS_CACHE: Dict[int, dict] = {}


def _entity_uri(kind: str, label: str) -> URIRef:
    safe = "".join(c if c.isalnum() else "_" for c in (label or "").lower())[:80]
    return VIG[f"{kind}/{safe}"]


def _symptom_label(raw: str) -> str:
    return canonical_event(raw or "") or ""


def _parse_regions(regions_json: Optional[str]) -> List[str]:
    if not regions_json:
        return []
    try:
        data = json.loads(regions_json)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [normalize_label(str(k), kind="region") for k in data.keys() if k]
    if isinstance(data, list):
        return [normalize_label(str(k), kind="region") for k in data if k]
    return []


def build_rdf_store(db: Session, project_id: Optional[int] = None) -> Graph:
    """Materialize drug→caused→symptom (+ region) triples from Signal + Alert rows."""
    g = Graph()
    g.bind("vig", VIG)
    g.bind("rdfs", RDFS)
    g.bind("region", REGION)

    # Prefer strongest PRR/strength when the same drug→AE appears multiple times
    pair_metrics: Dict[tuple, dict] = {}

    def _ingest_signal_row(s: Signal) -> None:
        drug = canonical_product(s.drug or "") or normalize_label(s.drug or "", kind="product")
        sym = _symptom_label(s.meddra_pt or s.symptom or "")
        if not drug or not sym:
            return
        key = (drug, sym.lower())
        prr = float(s.prr or 0)
        prev = pair_metrics.get(key)
        regions = _parse_regions(getattr(s, "regions_json", None))
        if prev is None or prr >= float(prev.get("prr") or 0):
            pair_metrics[key] = {
                "drug": drug,
                "symptom": sym,
                "prr": prr,
                "ror": float(s.ror or 0) if s.ror is not None else None,
                "strength": s.strength or "WEAK",
                "severity": s.severity,
                "soc": s.meddra_soc,
                "regions": list(dict.fromkeys((prev or {}).get("regions", []) + regions)),
                "signal_id": s.id,
            }
        else:
            prev["regions"] = list(dict.fromkeys(prev.get("regions", []) + regions))

    sig_q = db.query(Signal)
    if project_id is not None:
        sig_q = sig_q.filter(_legacy_project_clause(Signal.project_id, project_id))
    for s in sig_q.all():
        _ingest_signal_row(s)

    # Absolute sync: every Alert must have a corresponding drug→AE edge
    alert_q = db.query(Alert)
    if project_id is not None:
        alert_q = alert_q.filter(_legacy_project_clause(Alert.project_id, project_id))
    for a in alert_q.all():
        if a.signal_id:
            sig = db.query(Signal).filter(Signal.id == a.signal_id).first()
            if sig:
                _ingest_signal_row(sig)
                continue
        drug = canonical_product(a.drug or "") or normalize_label(a.drug or "", kind="product")
        sym = _symptom_label(a.symptom or "")
        if not drug or not sym:
            continue
        key = (drug, sym.lower())
        if key not in pair_metrics:
            pair_metrics[key] = {
                "drug": drug,
                "symptom": sym,
                "prr": 0.0,
                "ror": None,
                "strength": "STRONG" if (a.severity or "") in ("Critical", "High") else "MODERATE",
                "severity": a.severity,
                "soc": None,
                "regions": [],
                "signal_id": a.signal_id,
                "from_alert": True,
            }

    for meta in pair_metrics.values():
        drug_uri = _entity_uri("drug", meta["drug"])
        sym_uri = _entity_uri("symptom", meta["symptom"])
        g.add((drug_uri, RDF.type, VIG.Drug))
        g.add((sym_uri, RDF.type, VIG.Symptom))
        g.add((drug_uri, RDFS.label, Literal(meta["drug"])))
        g.add((sym_uri, RDFS.label, Literal(meta["symptom"])))
        g.add((drug_uri, VIG.caused, sym_uri))
        # Pair-level metrics as drug annotations (avoid symptom-global overwrite)
        g.add((drug_uri, VIG.signalPrr, Literal(f"{meta['symptom'].lower()}|{meta['prr']}|{meta['strength']}")))
        g.add((sym_uri, VIG.prr, Literal(meta["prr"])))
        g.add((sym_uri, VIG.strength, Literal(meta["strength"])))
        if meta.get("soc"):
            g.add((sym_uri, VIG.soc, Literal(meta["soc"])))
        if meta.get("severity"):
            g.add((sym_uri, VIG.severity, Literal(meta["severity"])))
        for reg_name in meta.get("regions") or []:
            if not reg_name:
                continue
            geo_uri = REGION[reg_name.replace(" ", "_").replace("/", "_")]
            g.add((geo_uri, RDF.type, VIG.Region))
            g.add((geo_uri, RDFS.label, Literal(reg_name)))
            g.add((sym_uri, VIG.reportedIn, geo_uri))
            g.add((drug_uri, VIG.reportedIn, geo_uri))

    post_q = (
        db.query(ProcessedPost, RawPost)
        .join(RawPost, ProcessedPost.raw_id == RawPost.id)
        .filter(ProcessedPost.ae_flag.is_(True))
    )
    if project_id is not None:
        post_q = post_q.filter(_legacy_project_clause(RawPost.project_id, project_id))

    for proc, raw in post_q.all():
        geo = normalize_label(raw.country or raw.region or "Global", kind="region") or "Global"
        geo_uri = REGION[geo.replace(" ", "_").replace("/", "_")]
        g.add((geo_uri, RDF.type, VIG.Region))
        g.add((geo_uri, RDFS.label, Literal(geo)))
        if raw.country:
            g.add((geo_uri, VIG.countryCode, Literal(raw.country)))

        try:
            ent = json.loads(proc.entities_json or "{}")
        except json.JSONDecodeError:
            continue

        drugs = []
        for d in ent.get("drugs", []):
            canon = canonical_product(d.get("normalized") or d.get("text") or "")
            if canon:
                drugs.append(canon)
        symptoms = [
            _symptom_label(s.get("normalized") or s.get("pt") or "")
            for s in ent.get("symptoms", [])
            if s.get("normalized") or s.get("pt")
        ]
        conditions = [c.get("normalized", "") for c in ent.get("conditions", []) if c.get("normalized")]

        for d in drugs:
            drug_uri = _entity_uri("drug", d)
            g.add((drug_uri, RDF.type, VIG.Drug))
            g.add((drug_uri, RDFS.label, Literal(d)))
            for sym in symptoms:
                if not sym:
                    continue
                sym_uri = _entity_uri("symptom", sym)
                g.add((sym_uri, RDF.type, VIG.Symptom))
                g.add((sym_uri, RDFS.label, Literal(sym)))
                g.add((drug_uri, VIG.caused, sym_uri))
                g.add((drug_uri, VIG.reportedIn, geo_uri))
                g.add((sym_uri, VIG.reportedIn, geo_uri))
            for cond in conditions:
                cond_uri = _entity_uri("condition", cond)
                g.add((cond_uri, RDF.type, VIG.Condition))
                g.add((cond_uri, RDFS.label, Literal(cond)))
                g.add((drug_uri, VIG.coReportedWith, cond_uri))
                g.add((cond_uri, VIG.reportedIn, geo_uri))

    # STITCH molecular gating — protein/CYP edges with confidence ≥ 0.700
    drug_labels = sorted(
        {
            str(o)
            for s, p, o in g.triples((None, RDFS.label, None))
            if (s, RDF.type, VIG.Drug) in g
        }
    )
    n_mol = enrich_graph(g, drug_labels, allow_live=False)
    if n_mol:
        logger.info("STITCH enrichment added %s molecular edges (offline KB)", n_mol)

    return g


def _graph_signature(db: Session, project_id: Optional[int]) -> tuple:
    from sqlalchemy import func

    pid = project_id or 0
    sig_n = db.query(func.count(Signal.id))
    post_n = db.query(func.count(ProcessedPost.id))
    if project_id is not None:
        sig_n = sig_n.filter(_legacy_project_clause(Signal.project_id, project_id))
        post_n = post_n.join(RawPost, ProcessedPost.raw_id == RawPost.id).filter(
            _legacy_project_clause(RawPost.project_id, project_id)
        )
    return (_GRAPH_BUILD_VERSION, pid, sig_n.scalar() or 0, post_n.scalar() or 0)


def get_graph(db: Session, project_id: Optional[int] = None) -> Graph:
    """Per-project cached in-memory graph."""
    pid = project_id or 0
    sig = _graph_signature(db, project_id)
    with _LOCK:
        if pid in _GRAPH_CACHE and _GRAPH_SIG.get(pid) == sig:
            return _GRAPH_CACHE[pid]
        g = build_rdf_store(db, project_id)
        _GRAPH_CACHE[pid] = g
        _GRAPH_SIG[pid] = sig
        _FILTER_OPTS_CACHE.pop(pid, None)
        return g


def _legacy_project_clause(col, project_id: Optional[int]):
    """Include rows for this project plus legacy rows where project_id is 0/NULL."""
    from sqlalchemy import or_

    if project_id is None:
        return True
    return or_(col == project_id, col.is_(None), col == 0)


def kg_filter_options(db: Session, project_id: Optional[int] = None) -> dict[str, List[str]]:
    """Dropdown values that are operable on the KG (have nodes / adverse edges).

    Earlier versions harvested every NER hit on every post, so the UI listed drugs
    that never formed a Signal or AE edge — selecting them showed an empty graph.
    Options are now limited to:
      • product / event labels on Signal rows (same strings as global KG nodes)
      • entities on AE-flagged posts only (same population RDF/SPARQL ingests)
      • geo from AE-flagged posts only
    """
    pid = project_id or 0
    sig = _graph_signature(db, project_id)
    with _LOCK:
        cached = _FILTER_OPTS_CACHE.get(pid)
        if cached and cached.get("_sig") == sig:
            return cached["data"]

    drugs: Set[str] = set()
    symptoms: Set[str] = set()
    conditions: Set[str] = set()
    countries: Set[str] = set()
    regions: Set[str] = set()

    def _collect(scope: Optional[int]) -> None:
        sig_q = db.query(Signal)
        if scope is not None:
            sig_q = sig_q.filter(_legacy_project_clause(Signal.project_id, scope))
        for s in sig_q.all():
            # Exact Signal.drug string — matches pipeline.build_graph node labels.
            raw_drug = (s.drug or "").strip()
            if raw_drug:
                drugs.add(raw_drug)
            canon = canonical_product(raw_drug)
            if canon:
                drugs.add(canon)
            ev_raw = (s.meddra_pt or s.symptom or "").strip()
            if ev_raw:
                symptoms.add(ev_raw)
            ev = canonical_event(ev_raw)
            if ev:
                symptoms.add(ev)

        # AE-flagged posts: geography only. Product/event dropdowns stay Signal-backed
        # so we never list NER mentions that have no disproportionality pair / KG edge.
        post_q = (
            db.query(RawPost)
            .join(ProcessedPost, ProcessedPost.raw_id == RawPost.id)
            .filter(ProcessedPost.ae_flag.is_(True))
        )
        if scope is not None:
            post_q = post_q.filter(_legacy_project_clause(RawPost.project_id, scope))
        for raw in post_q.all():
            if raw.country:
                countries.add(normalize_label(raw.country, kind="region") or raw.country)
            if raw.region:
                regions.add(normalize_label(raw.region, kind="region") or raw.region)

            # Conditions that co-occur on AE posts with a signal product can appear
            # as indication edges in RDF; only keep if the post also names a known drug.
            try:
                proc = (
                    db.query(ProcessedPost)
                    .filter(ProcessedPost.raw_id == raw.id)
                    .first()
                )
                if not proc:
                    continue
                ent = json.loads(proc.entities_json or "{}")
            except json.JSONDecodeError:
                continue
            post_drugs = set()
            for d in ent.get("drugs", []):
                text = (d.get("normalized") or d.get("text") or "").strip()
                if text:
                    post_drugs.add(text.lower())
                canon = canonical_product(text)
                if canon:
                    post_drugs.add(canon.lower())
            known = {x.lower() for x in drugs}
            if not post_drugs.intersection(known):
                continue
            for c in ent.get("conditions", []):
                from ..nlp.condition_norm import canonical_condition

                text = (c.get("normalized") or c.get("text") or "").strip()
                if text:
                    conditions.add(text)
                canon = canonical_condition(text)
                if canon:
                    conditions.add(canon)

    _collect(project_id)
    if project_id is not None and not any([drugs, symptoms, conditions, countries, regions]):
        _collect(None)

    data = {
        "drugs": dedupe_labels(list(drugs), kind="product"),
        "symptoms": dedupe_labels(list(symptoms), kind="event"),
        "conditions": dedupe_labels(list(conditions), kind="condition"),
        "countries": dedupe_labels(list(countries), kind="region"),
        "regions": dedupe_labels(list(regions), kind="region"),
    }
    with _LOCK:
        _FILTER_OPTS_CACHE[pid] = {"_sig": sig, "data": data}
    return data


def _rdf_label(g: Graph, uri: URIRef) -> str:
    for o in g.objects(uri, RDFS.label):
        return str(o)
    return str(uri).rsplit("/", 1)[-1].replace("_", " ")


def _label_matches(label: str, param: str) -> bool:
    if not param:
        return True
    l = (label or "").lower().strip()
    p = param.lower().strip()
    return l == p or p in l or l in p


def _pair_metrics(db: Session, project_id: Optional[int]) -> Dict[tuple, dict]:
    """(drug, symptom_lower) → disproportionality metrics from Signal rows."""
    out: Dict[tuple, dict] = {}
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(_legacy_project_clause(Signal.project_id, project_id))
    for s in q.all():
        drug = canonical_product(s.drug or "")
        sym = _symptom_label(s.meddra_pt or s.symptom or "")
        if not drug or not sym:
            continue
        key = (drug, sym.lower())
        prr = float(s.prr or 0)
        prev = out.get(key)
        if prev is None or prr >= float(prev.get("prr") or 0):
            out[key] = {
                "prr": prr,
                "ror": float(s.ror or 0) if s.ror is not None else None,
                "strength": s.strength or "WEAK",
                "severity": s.severity,
                "post_count": int(s.post_count or 0),
                "signal_id": s.id,
            }
    return out


def sparql_subgraph(
    db: Session,
    *,
    project_id: Optional[int] = None,
    drug_param: str = "",
    symptom_param: str = "",
    region_param: str = "",
    country_param: str = "",
    condition_param: str = "",
    focus_node: Optional[str] = None,
    with_story: bool = True,
) -> dict[str, Any]:
    """Walk the in-memory RDF store into a UI graph (no SPARQL cartesian LIMIT truncation).

    Unfiltered views return all drug→AE edges. Region / condition / STITCH protein
    context is attached when a drug or AE filter is active (keeps the default graph readable).
    """
    g = get_graph(db, project_id)
    metrics = _pair_metrics(db, project_id)
    geo_filter = (country_param or region_param or "").strip()
    drug_f = (drug_param or "").strip()
    symptom_f = (symptom_param or "").strip()
    condition_f = (condition_param or "").strip()
    focused = bool(drug_f or symptom_f or geo_filter or condition_f)

    nodes: Dict[str, dict] = {}
    edges: List[dict] = []
    edge_keys: set[str] = set()
    paths: List[dict] = []
    path_keys: set[str] = set()

    def _node(nid: str, label: str, ntype: str) -> dict:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "type": ntype, "degree": 0}
        return nodes[nid]

    def _bump(nid: str) -> None:
        if nid in nodes:
            nodes[nid]["degree"] += 1

    # --- Core adverse edges (complete; no row LIMIT) ---
    matched_drugs: Set[str] = set()
    matched_syms: Set[str] = set()

    for drug_uri, _, sym_uri in g.triples((None, VIG.caused, None)):
        if (drug_uri, RDF.type, VIG.Drug) not in g:
            continue
        if (sym_uri, RDF.type, VIG.Symptom) not in g:
            continue
        dlabel = _rdf_label(g, drug_uri)
        slabel = _rdf_label(g, sym_uri)
        if not _label_matches(dlabel, drug_f):
            continue
        if not _label_matches(slabel, symptom_f):
            continue

        # Geo filter: require at least one matching region on the symptom (or drug)
        if geo_filter:
            geo_ok = False
            for reg in g.objects(sym_uri, VIG.reportedIn):
                if _label_matches(_rdf_label(g, reg), geo_filter):
                    geo_ok = True
                    break
            if not geo_ok:
                for reg in g.objects(drug_uri, VIG.reportedIn):
                    if _label_matches(_rdf_label(g, reg), geo_filter):
                        geo_ok = True
                        break
            if not geo_ok:
                continue

        # Condition filter: drug must co-report the condition
        if condition_f:
            cond_ok = False
            for cond in g.objects(drug_uri, VIG.coReportedWith):
                if _label_matches(_rdf_label(g, cond), condition_f):
                    cond_ok = True
                    break
            if not cond_ok:
                continue

        drug_id = str(drug_uri)
        sym_id = str(sym_uri)
        _node(drug_id, dlabel, "drug")
        _node(sym_id, slabel, "symptom")
        matched_drugs.add(drug_id)
        matched_syms.add(sym_id)

        m = metrics.get((dlabel, slabel.lower())) or metrics.get(
            (canonical_product(dlabel) or dlabel, slabel.lower())
        ) or {}
        prr_val = float(m["prr"]) if m.get("prr") is not None else None
        strength_val = m.get("strength")

        ek = f"{drug_id}|{sym_id}"
        if ek not in edge_keys:
            edge_keys.add(ek)
            edges.append({
                "source": drug_id,
                "target": sym_id,
                "kind": "adverse",
                "prr": prr_val,
                "ror": m.get("ror"),
                "strength": strength_val,
                "severity": m.get("severity"),
                "post_count": m.get("post_count"),
                "signal_id": m.get("signal_id"),
            })
            _bump(drug_id)
            _bump(sym_id)

        pk = f"{dlabel}|{slabel}"
        if pk not in path_keys:
            path_keys.add(pk)
            paths.append({
                "drug": dlabel,
                "symptom": slabel,
                "prr": prr_val,
                "ror": m.get("ror"),
                "strength": strength_val,
                "severity": m.get("severity"),
                "post_count": m.get("post_count"),
                "signal_id": m.get("signal_id"),
                "regions": [],
                "condition": None,
            })

    # --- Regions always (location nodes); conditions/proteins when focused ---
    for sym_id in list(matched_syms):
        sym_uri = URIRef(sym_id)
        n_reg = 0
        for reg in g.objects(sym_uri, VIG.reportedIn):
            if n_reg >= 5:
                break
            rlabel = _rdf_label(g, reg)
            if geo_filter and not _label_matches(rlabel, geo_filter):
                continue
            rid = str(reg)
            _node(rid, rlabel, "region")
            rk = f"{sym_id}|{rid}"
            if rk not in edge_keys:
                edge_keys.add(rk)
                edges.append({"source": sym_id, "target": rid, "kind": "region"})
                _bump(sym_id)
                _bump(rid)
                n_reg += 1
            for p in paths:
                if p["symptom"] == _rdf_label(g, sym_uri) and rlabel not in p["regions"]:
                    p["regions"].append(rlabel)

    if focused:
        for drug_id in list(matched_drugs):
            drug_uri = URIRef(drug_id)
            # conditions
            for cond in g.objects(drug_uri, VIG.coReportedWith):
                clabel = _rdf_label(g, cond)
                if condition_f and not _label_matches(clabel, condition_f):
                    continue
                cid = str(cond)
                _node(cid, clabel, "condition")
                ck = f"{drug_id}|{cid}"
                if ck not in edge_keys:
                    edge_keys.add(ck)
                    edges.append({"source": drug_id, "target": cid, "kind": "condition"})
                    _bump(drug_id)
                    _bump(cid)
                for p in paths:
                    if p["drug"] == _rdf_label(g, drug_uri) and not p.get("condition"):
                        p["condition"] = clabel

            # STITCH binds (cap per drug)
            n_prot = 0
            for prot in g.objects(drug_uri, VIG.binds):
                if n_prot >= 6:
                    break
                plabel = _rdf_label(g, prot)
                pid = str(prot)
                conf = None
                for c in g.objects(prot, VIG.confidence):
                    try:
                        conf = float(c)
                    except (TypeError, ValueError):
                        conf = None
                    break
                tkind = None
                for t in g.objects(prot, VIG.targetKind):
                    tkind = str(t)
                    break
                node = _node(pid, plabel, "protein")
                node["confidence"] = conf
                node["target_kind"] = tkind
                pk_edge = f"{drug_id}|binds|{pid}"
                if pk_edge not in edge_keys:
                    edge_keys.add(pk_edge)
                    edges.append({
                        "source": drug_id,
                        "target": pid,
                        "kind": "binds",
                        "confidence": conf,
                    })
                    _bump(drug_id)
                    _bump(pid)
                    n_prot += 1

    node_list = list(nodes.values())
    paths.sort(key=lambda p: (p.get("prr") or 0), reverse=True)

    if focus_node:
        focus_ids = {focus_node}
        for e in edges:
            if e["source"] == focus_node:
                focus_ids.add(e["target"])
            if e["target"] == focus_node:
                focus_ids.add(e["source"])
        node_list = [n for n in node_list if n["id"] in focus_ids]
        edges = [e for e in edges if e["source"] in focus_ids and e["target"] in focus_ids]

    stats = {"node_count": len(node_list), "edge_count": len(edges)}
    filters = {
        "drug": drug_param,
        "symptom": symptom_param,
        "region": region_param,
        "country": country_param,
        "condition": condition_param,
        "focus_node": focus_node,
    }
    hubs = sorted(node_list, key=lambda n: n.get("degree", 0), reverse=True)[:8]

    story = build_kg_story(paths[:40], filters=filters, stats=stats) if with_story else None
    filter_options = kg_filter_options(db, project_id)

    jsonld = {
        "@context": {"vig": str(VIG), "rdfs": str(RDFS)},
        "@graph": [
            {"@id": n["id"], "@type": n["type"], "rdfs:label": n["label"]}
            for n in node_list
        ],
    }

    return {
        "nodes": node_list,
        "edges": edges,
        # Full path catalog for drug↔AE explorer (story still uses top slice above)
        "paths": paths[:2000],
        "stats": stats,
        "hubs": [
            {"id": h["id"], "label": h["label"], "type": h["type"], "centrality": h["degree"]}
            for h in hubs
        ],
        "filters": filters,
        "filter_options": filter_options,
        "story": story,
        "jsonld": jsonld,
        "engine": "rdflib",
        "molecular_gating": {"source": "STITCH/STRING offline KB", "species": 9606, "min_confidence": 0.700},
        "legend": {
            "drug": "Product (blue)",
            "symptom": "Adverse event / symptom (red)",
            "condition": "Comorbidity / indication context (amber)",
            "region": "Country or region (slate)",
            "protein": "STITCH protein / CYP target (teal, conf≥0.70)",
        },
    }
