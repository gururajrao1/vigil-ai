"""STITCH / STRING molecular enrichment for the RDF knowledge graph.

Offline-first: curated human (species=9606) drug→protein / CYP confidence
vectors ship in-repo. Optional live STRING/STITCH-compatible API enrichment
runs when reachable; edges below confidence 0.700 are dropped.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import httpx
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, RDFS

from ..config import settings

logger = logging.getLogger("vigilai.stitch")

VIG = Namespace("http://vigilai.dev/ontology#")
CONFIDENCE_FLOOR = 0.700
SPECIES = 9606

# Curated offline STITCH-style edges: drug → (target, confidence, kind)
# Confidence is STITCH/STRING combined score scaled 0–1.
_OFFLINE_KB: Dict[str, List[Tuple[str, float, str]]] = {
    "warfarin": [
        ("CYP2C9", 0.95, "cyp"),
        ("VKORC1", 0.99, "target"),
        ("CYP3A4", 0.72, "cyp"),
    ],
    "clopidogrel": [
        ("CYP2C19", 0.97, "cyp"),
        ("P2RY12", 0.94, "target"),
    ],
    "simvastatin": [
        ("CYP3A4", 0.91, "cyp"),
        ("HMGCR", 0.99, "target"),
        ("SLCO1B1", 0.88, "transporter"),
    ],
    "atorvastatin": [
        ("CYP3A4", 0.89, "cyp"),
        ("HMGCR", 0.99, "target"),
        ("SLCO1B1", 0.85, "transporter"),
    ],
    "metformin": [
        ("SLC22A1", 0.82, "transporter"),
        ("PRKAB1", 0.78, "target"),
    ],
    "sertraline": [
        ("CYP2D6", 0.86, "cyp"),
        ("SLC6A4", 0.97, "target"),
        ("CYP2C19", 0.74, "cyp"),
    ],
    "fluoxetine": [
        ("CYP2D6", 0.94, "cyp"),
        ("SLC6A4", 0.98, "target"),
    ],
    "ibuprofen": [
        ("PTGS1", 0.91, "target"),
        ("PTGS2", 0.93, "target"),
        ("CYP2C9", 0.71, "cyp"),
    ],
    "acetaminophen": [
        ("CYP2E1", 0.88, "cyp"),
        ("PTGS1", 0.70, "target"),
    ],
    "paracetamol": [
        ("CYP2E1", 0.88, "cyp"),
        ("PTGS1", 0.70, "target"),
    ],
    "amiodarone": [
        ("CYP3A4", 0.90, "cyp"),
        ("CYP2C9", 0.81, "cyp"),
        ("KCNH2", 0.84, "target"),
    ],
    "pembrolizumab": [
        ("PDCD1", 0.99, "target"),
    ],
    "nivolumab": [
        ("PDCD1", 0.99, "target"),
    ],
    "imatinib": [
        ("ABL1", 0.99, "target"),
        ("KIT", 0.95, "target"),
        ("CYP3A4", 0.80, "cyp"),
    ],
    "tamoxifen": [
        ("CYP2D6", 0.96, "cyp"),
        ("ESR1", 0.98, "target"),
    ],
}


def _entity_uri(kind: str, label: str):
    from rdflib import URIRef

    safe = "".join(c if c.isalnum() else "_" for c in (label or "").lower())[:80]
    return URIRef(str(VIG[f"{kind}/{safe}"]))


def offline_targets(drug: str) -> List[Tuple[str, float, str]]:
    key = (drug or "").strip().lower()
    hits = list(_OFFLINE_KB.get(key, []))
    return [(t, c, k) for t, c, k in hits if c >= CONFIDENCE_FLOOR]


def fetch_string_targets(drug: str, timeout: float = 6.0) -> List[Tuple[str, float, str]]:
    """Optional live enrichment via STRING-compatible API (species=9606).

    Returns empty on any failure — callers must use offline KB.
    """
    base = settings.stitch_api_base
    if not base or not drug:
        return []
    try:
        with httpx.Client(timeout=timeout) as client:
            # Resolve chemical/protein name → STRING identifiers
            r = client.get(
                f"{base}/json/resolve",
                params={"identifier": drug, "species": SPECIES, "limit": 3},
            )
            if r.status_code >= 400:
                return []
            resolved = r.json()
            if not resolved:
                return []
            string_id = resolved[0].get("stringId") or resolved[0].get("preferredName")
            if not string_id:
                return []
            # Interaction partners (combined score is 0–1000 in STRING)
            r2 = client.get(
                f"{base}/json/interaction_partners",
                params={
                    "identifiers": string_id,
                    "species": SPECIES,
                    "limit": 12,
                },
            )
            if r2.status_code >= 400:
                return []
            out: List[Tuple[str, float, str]] = []
            for row in r2.json() or []:
                name = (
                    row.get("preferredName_B")
                    or row.get("preferredName")
                    or row.get("stringId_B")
                    or ""
                )
                score_raw = float(row.get("score") or row.get("escore") or 0)
                conf = score_raw / 1000.0 if score_raw > 1.0 else score_raw
                if name and conf >= CONFIDENCE_FLOOR:
                    kind = "cyp" if name.upper().startswith("CYP") else "target"
                    out.append((name, round(conf, 3), kind))
            return out
    except Exception as exc:
        logger.debug("STITCH/STRING live enrich failed for %s: %s", drug, exc)
        return []


def targets_for_drug(drug: str, *, allow_live: bool = True) -> List[Tuple[str, float, str]]:
    """Merge offline KB with optional live hits; drop below confidence floor."""
    merged: Dict[str, Tuple[float, str]] = {}
    for name, conf, kind in offline_targets(drug):
        merged[name.upper()] = (conf, kind)
    if allow_live:
        for name, conf, kind in fetch_string_targets(drug):
            key = name.upper()
            prev = merged.get(key)
            if not prev or conf > prev[0]:
                merged[key] = (conf, kind)
    return [(n, c, k) for n, (c, k) in sorted(merged.items(), key=lambda x: -x[1][0])]


def enrich_graph(g: Graph, drug_labels: List[str], *, allow_live: bool = False) -> int:
    """Add protein/CYP nodes and vig:binds edges for drugs already in the graph.

    Returns number of molecular edges added. Live API is off by default so
    graph builds stay offline-deterministic; set allow_live=True for enrichment jobs.
    """
    added = 0
    seen_drugs = {d.strip().lower() for d in drug_labels if d}
    for drug in sorted(seen_drugs):
        drug_uri = _entity_uri("drug", drug)
        g.add((drug_uri, RDF.type, VIG.Drug))
        g.add((drug_uri, RDFS.label, Literal(drug)))
        for target, conf, kind in targets_for_drug(drug, allow_live=allow_live):
            t_uri = _entity_uri("protein", target)
            g.add((t_uri, RDF.type, VIG.Protein))
            g.add((t_uri, RDFS.label, Literal(target)))
            g.add((t_uri, VIG.targetKind, Literal(kind)))
            g.add((t_uri, VIG.species, Literal(SPECIES)))
            g.add((drug_uri, VIG.binds, t_uri))
            g.add((drug_uri, VIG.bindingConfidence, Literal(conf)))
            # Also attach confidence on the protein for SPARQL filters
            g.add((t_uri, VIG.confidence, Literal(conf)))
            added += 1
    return added
