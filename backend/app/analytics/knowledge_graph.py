"""Drug-Symptom-Condition knowledge graph (new capability from the brief).

Builds a networkx graph from detected signals and returns a JSON projection
(nodes + edges + centrality) for the frontend force-directed visualization.
"""
from __future__ import annotations

from typing import Dict, List

import networkx as nx

_STRENGTH_WEIGHT = {"STRONG": 3.0, "MODERATE": 2.0, "WEAK": 1.0}


def build_graph(signals: List[dict], condition_links: List[dict] | None = None) -> Dict:
    """signals: list with drug, symptom, prr, strength, post_count, severity.

    condition_links: optional list of {drug, condition, count} for indication edges.
    """
    g = nx.Graph()

    for s in signals:
        drug = s["drug"]
        symptom = s["symptom"]
        g.add_node(f"drug::{drug}", label=drug, type="drug")
        g.add_node(f"symptom::{symptom}", label=symptom, type="symptom")
        weight = _STRENGTH_WEIGHT.get(s.get("strength", "WEAK"), 1.0) * max(1, s.get("post_count", 1))
        g.add_edge(
            f"drug::{drug}", f"symptom::{symptom}",
            weight=weight,
            prr=s.get("prr"),
            strength=s.get("strength"),
            severity=s.get("severity"),
            post_count=s.get("post_count"),
            kind="adverse",
        )

    for link in condition_links or []:
        drug = link["drug"]
        cond = link["condition"]
        g.add_node(f"drug::{drug}", label=drug, type="drug")
        g.add_node(f"condition::{cond}", label=cond, type="condition")
        g.add_edge(
            f"drug::{drug}", f"condition::{cond}",
            weight=float(link.get("count", 1)),
            kind="indication",
        )

    centrality = nx.degree_centrality(g) if g.number_of_nodes() else {}

    nodes = [
        {
            "id": nid,
            "label": data["label"],
            "type": data["type"],
            "centrality": round(centrality.get(nid, 0.0), 4),
            "degree": g.degree(nid),
        }
        for nid, data in g.nodes(data=True)
    ]
    edges = [
        {
            "source": u,
            "target": v,
            "weight": data.get("weight", 1.0),
            "prr": data.get("prr"),
            "strength": data.get("strength"),
            "severity": data.get("severity"),
            "post_count": data.get("post_count"),
            "kind": data.get("kind", "adverse"),
        }
        for u, v, data in g.edges(data=True)
    ]

    hubs = sorted(nodes, key=lambda n: n["centrality"], reverse=True)[:5]
    return {"nodes": nodes, "edges": edges, "hubs": hubs,
            "stats": {"node_count": len(nodes), "edge_count": len(edges)}}
