"""Heterogeneous ontology knowledge graph over VigilAI signals.

``analytics.knowledge_graph.build_graph`` stays the co-occurrence projection the
existing force-directed UI consumes. This module is the *typed* layer: nodes carry
an ontology namespace (drug, ATC class, chemical entity, MedDRA PT/SOC, device,
IMDRF failure) and edges carry a relation label, so the graph can be reasoned over
or exported to a GNN instead of only drawn.

Relations
    HAS_ATC_CLASS          drug     -> atc (L4/L5)
    BELONGS_TO             atc      -> atc (child -> parent), pt -> soc
    HAS_CHEMICAL_STRUCTURE drug     -> chebi
    CAUSES_EVENT           drug/dev -> meddra pt
    MAPPED_TO              device   -> gmdn, device -> imdrf failure

NetworkX is the primary backend. PyTorch Geometric export is attempted only when
``torch_geometric`` is importable, so it is never a dependency.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import networkx as nx
from sqlalchemy.orm import Session

from ..models import Signal
from ..nlp.ontology_engine import device_mapper, drug_chemical_mapper, meddra_mapper
from ..nlp.ontology_engine.models import ONTOLOGY_VERSION, SURROGATE_DISCLAIMER

_STRENGTH_WEIGHT = {"STRONG": 3.0, "MODERATE": 2.0, "WEAK": 1.0}

NODE_TYPES = ("drug", "device", "atc", "chebi", "meddra_pt", "meddra_soc", "imdrf")
EDGE_TYPES = (
    "HAS_ATC_CLASS",
    "BELONGS_TO",
    "HAS_CHEMICAL_STRUCTURE",
    "CAUSES_EVENT",
    "MAPPED_TO",
)


def _nid(kind: str, label: str) -> str:
    return f"{kind}::{label}"


def _add_node(g: nx.MultiDiGraph, kind: str, label: str, **attrs) -> str:
    node_id = _nid(kind, label)
    if node_id not in g:
        g.add_node(node_id, label=label, type=kind, **attrs)
    else:
        g.nodes[node_id].update({k: v for k, v in attrs.items() if v is not None})
    return node_id


def _add_edge(g: nx.MultiDiGraph, src: str, dst: str, relation: str, **attrs) -> None:
    g.add_edge(src, dst, key=relation, relation=relation, **attrs)


def _attach_drug(g: nx.MultiDiGraph, product: str) -> Optional[str]:
    mapped = drug_chemical_mapper.map_drug(product, with_similarity=False)
    if not mapped.matched:
        return None
    drug_id = _add_node(g, "drug", mapped.preferred_generic or product,
                        cui=mapped.cui, rxnorm=mapped.rxnorm_id, atc=mapped.atc_code)

    previous: Optional[str] = None
    for level in mapped.atc_levels:
        atc_id = _add_node(g, "atc", level.code, atc_label=level.label,
                           atc_level=level.level, level_name=level.level_name)
        if previous:
            _add_edge(g, atc_id, previous, "BELONGS_TO", weight=1.0)
        previous = atc_id
    if mapped.atc_levels:
        deepest = _nid("atc", mapped.atc_levels[-1].code)
        _add_edge(g, drug_id, deepest, "HAS_ATC_CLASS", weight=1.0)

    if mapped.chemical and mapped.chemical.chebi_id:
        chebi_id = _add_node(g, "chebi", mapped.chemical.chebi_id,
                             smiles=mapped.chemical.smiles,
                             formula=mapped.chemical.formula)
        _add_edge(g, drug_id, chebi_id, "HAS_CHEMICAL_STRUCTURE", weight=1.0)
    return drug_id


def _attach_device(g: nx.MultiDiGraph, product: str, failure: str) -> Optional[str]:
    mapped = device_mapper.map_device(product, failure)
    if not mapped.matched:
        return None
    device_id = _add_node(
        g, "device", mapped.canonical_device or product,
        cui=mapped.cui, gmdn=mapped.gmdn_code, emdn=mapped.emdn_code,
        fda_class=mapped.fda_class, eu_mdr_class=mapped.eu_mdr_class,
        is_samd=mapped.is_samd,
    )
    if mapped.imdrf_code:
        imdrf_id = _add_node(g, "imdrf", mapped.imdrf_term or mapped.imdrf_code,
                             code=mapped.imdrf_code)
        _add_edge(g, device_id, imdrf_id, "MAPPED_TO", weight=1.0)
    return device_id


def build_ontology_graph(
    db: Session,
    *,
    project_id: Optional[int] = None,
    product: Optional[str] = None,
    limit: int = 300,
) -> dict:
    """Build the typed graph from stored signals and return a JSON projection."""
    q = db.query(Signal)
    if project_id is not None:
        q = q.filter(Signal.project_id == project_id)
    if product:
        q = q.filter(Signal.drug == product.strip().lower())
    signals = q.order_by(Signal.post_count.desc()).limit(max(1, limit)).all()

    g = nx.MultiDiGraph()
    skipped = 0

    for sig in signals:
        name = (sig.drug or "").strip().lower()
        if not name:
            continue
        is_device = (sig.product_type or "drug") == "device" or bool(sig.device_gmdn)
        source_id = (
            _attach_device(g, name, sig.imdrf_term or sig.symptom or "")
            if is_device else _attach_drug(g, name)
        )
        if source_id is None:
            source_id = _add_node(g, "device" if is_device else "drug", name,
                                  unmapped=True)
            skipped += 1

        chain = meddra_mapper.map_event(sig.meddra_pt or sig.symptom or "")
        pt_label = chain.pt or (sig.symptom or "").strip().title()
        if not pt_label:
            continue
        pt_id = _add_node(g, "meddra_pt", pt_label, cui=chain.cui, hlt=chain.hlt,
                          hlgt=chain.hlgt, snomed_ct=chain.snomed_ct, oae=chain.oae)
        _add_edge(
            g, source_id, pt_id, "CAUSES_EVENT",
            weight=_STRENGTH_WEIGHT.get(sig.strength or "WEAK", 1.0) * max(1, sig.post_count or 1),
            prr=sig.prr, eb05=sig.eb05, ic025=sig.ic025, strength=sig.strength,
            post_count=sig.post_count, sdr_flag=bool(sig.sdr_flag),
            severity=sig.severity, signal_id=sig.id,
        )
        soc_label = chain.soc or sig.meddra_soc
        if soc_label:
            soc_id = _add_node(g, "meddra_soc", soc_label, soc_code=chain.soc_code)
            _add_edge(g, pt_id, soc_id, "BELONGS_TO", weight=1.0)

    undirected = g.to_undirected(as_view=False)
    centrality = nx.degree_centrality(undirected) if g.number_of_nodes() else {}

    nodes: List[dict] = [
        {
            "id": nid,
            "label": data.get("label"),
            "type": data.get("type"),
            "centrality": round(centrality.get(nid, 0.0), 4),
            "degree": g.degree(nid),
            "attrs": {k: v for k, v in data.items() if k not in {"label", "type"}},
        }
        for nid, data in g.nodes(data=True)
    ]
    edges: List[dict] = [
        {
            "source": u,
            "target": v,
            "relation": data.get("relation", key),
            **{k: val for k, val in data.items() if k != "relation"},
        }
        for u, v, key, data in g.edges(keys=True, data=True)
    ]

    by_type: Dict[str, int] = {}
    for node in nodes:
        by_type[node["type"]] = by_type.get(node["type"], 0) + 1
    by_relation: Dict[str, int] = {}
    for edge in edges:
        by_relation[edge["relation"]] = by_relation.get(edge["relation"], 0) + 1

    hubs = sorted(nodes, key=lambda n: n["centrality"], reverse=True)[:8]

    return {
        "nodes": nodes,
        "edges": edges,
        "hubs": hubs,
        "node_types": list(NODE_TYPES),
        "edge_types": list(EDGE_TYPES),
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "signals_used": len(signals),
            "unmapped_products": skipped,
            "nodes_by_type": by_type,
            "edges_by_relation": by_relation,
            "pyg_available": pyg_available(),
        },
        "how_to_read": (
            "Typed relations let you trace a signal from ingredient to ATC class to "
            "chemistry and from event term to organ class in one traversal. "
            "Co-occurrence weights live on CAUSES_EVENT edges; the ontology edges "
            "carry no statistics by design."
        ),
        "ontology_version": ONTOLOGY_VERSION,
        "disclaimer": SURROGATE_DISCLAIMER,
    }


def pyg_available() -> bool:
    try:  # pragma: no cover - optional dependency
        import torch_geometric  # noqa: F401,PLC0415

        return True
    except Exception:
        return False


def to_pyg(graph: dict):  # pragma: no cover - optional dependency
    """Export the JSON projection to a PyTorch Geometric ``HeteroData``.

    Returns ``None`` when torch_geometric is not installed; callers must treat the
    export as optional.
    """
    try:
        import torch  # noqa: PLC0415
        from torch_geometric.data import HeteroData  # noqa: PLC0415
    except Exception:
        return None

    data = HeteroData()
    index_of: Dict[str, int] = {}
    per_type: Dict[str, List[str]] = {}
    for node in graph.get("nodes", []):
        bucket = per_type.setdefault(node["type"], [])
        index_of[node["id"]] = len(bucket)
        bucket.append(node["id"])
    for node_type, ids in per_type.items():
        data[node_type].num_nodes = len(ids)
        data[node_type].node_ids = ids

    type_of = {n["id"]: n["type"] for n in graph.get("nodes", [])}
    buckets: Dict[tuple, List[List[int]]] = {}
    for edge in graph.get("edges", []):
        src, dst = edge["source"], edge["target"]
        if src not in index_of or dst not in index_of:
            continue
        key = (type_of[src], edge["relation"], type_of[dst])
        buckets.setdefault(key, [[], []])
        buckets[key][0].append(index_of[src])
        buckets[key][1].append(index_of[dst])
    for key, (rows, cols) in buckets.items():
        data[key].edge_index = torch.tensor([rows, cols], dtype=torch.long)
    return data
