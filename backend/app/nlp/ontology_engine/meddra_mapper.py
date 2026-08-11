"""Event verbatim → surrogate CUI → LLT → PT → HLT → HLGT → SOC.

The PT/SOC layer stays the existing ``app.nlp.meddra`` surrogate so stored signal
coding and the hierarchy never disagree; this module adds the intermediate MedDRA
tiers (HLT/HLGT), the LLT layer of patient-language synonyms, and the SNOMED/OAE/
CUI crosswalk fields.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from ..meddra import SOC, map_term
from . import crosswalk, dictionary_store
from .models import AuditStamp, MeddraChain

_LLT_INDEX: Dict[str, dict] = {}
_PT_INDEX: Dict[str, dict] = {}
_INDEX_LOCK = threading.Lock()
_INDEX_READY = False


def _clean(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _build_index() -> None:
    global _INDEX_READY
    if _INDEX_READY:
        return
    with _INDEX_LOCK:
        if _INDEX_READY:
            return
        for chain in dictionary_store.meddra_chains():
            pt = chain.get("pt")
            if not pt:
                continue
            _PT_INDEX[_clean(pt)] = chain
            for llt in chain.get("llts") or []:
                _LLT_INDEX.setdefault(_clean(llt), chain)
        _INDEX_READY = True


def reload_index() -> None:
    """Drop the memoized index (tests / dictionary hot-swap)."""
    global _INDEX_READY
    with _INDEX_LOCK:
        _LLT_INDEX.clear()
        _PT_INDEX.clear()
        _INDEX_READY = False


def _audit(online: bool) -> AuditStamp:
    return AuditStamp(
        source="meddra_hierarchy_surrogate",
        online_enrichment=online,
        dictionaries=["meddra_hierarchy_surrogate.json", "app.nlp.meddra"],
    )


def _substring_chain(key: str) -> Optional[tuple[dict, str]]:
    """Longest LLT contained in a free-text phrase ("rash after the second dose")."""
    best: Optional[tuple[dict, str]] = None
    for llt, chain in _LLT_INDEX.items():
        if len(llt) < 5 or llt not in key:
            continue
        if best is None or len(llt) > len(best[1]):
            best = (chain, llt)
    return best


def _token_subset_chain(key: str) -> Optional[tuple[dict, str]]:
    """LLT whose every word appears in the phrase ("my heart keeps racing")."""
    words = {w for w in key.replace("-", " ").split() if len(w) > 2}
    if len(words) < 2:
        return None
    best: Optional[tuple[dict, str]] = None
    for llt, chain in _LLT_INDEX.items():
        tokens = {t for t in llt.split() if len(t) > 2}
        if len(tokens) < 2 or not tokens.issubset(words):
            continue
        if best is None or len(tokens) > len(best[1].split()):
            best = (chain, llt)
    return best


def chain_for_pt(pt: str) -> Optional[dict]:
    """Raw surrogate chain row for a Preferred Term, if the hierarchy knows it."""
    _build_index()
    return _PT_INDEX.get(_clean(pt))


def map_event(verbatim: str, *, online: bool = False) -> MeddraChain:
    """Map any event surface form to the full 5-tier chain."""
    _build_index()
    key = _clean(verbatim)
    audit = _audit(online)

    if not key:
        return MeddraChain(verbatim=verbatim or "", matched=False,
                           match_method="empty", audit=audit)

    chain: Optional[dict] = None
    llt = key
    method = "unmatched"
    confidence = 0.0

    if key in _LLT_INDEX:
        chain, method, confidence = _LLT_INDEX[key], "llt_exact", 0.95
    elif key in _PT_INDEX:
        chain, method, confidence = _PT_INDEX[key], "pt_exact", 0.92
        llt = chain.get("pt", key)
    else:
        seed = map_term(key)
        if seed.get("matched"):
            chain = _PT_INDEX.get(_clean(seed["pt"]))
            if chain:
                method, confidence = "pt_via_surrogate_map", 0.85
            else:
                chain = {
                    "pt": seed["pt"],
                    "hlt": None,
                    "hlgt": None,
                    "soc_code": seed["soc_code"],
                }
                method, confidence = "pt_only_surrogate_map", 0.7
        else:
            hit = _substring_chain(key)
            if hit:
                chain, llt = hit[0], hit[1]
                method, confidence = "llt_substring", 0.6
            else:
                hit = _token_subset_chain(key)
                if hit:
                    chain, llt = hit[0], hit[1]
                    method, confidence = "llt_token_subset", 0.5

    if chain is None:
        soc_code = map_term(key).get("soc_code", "GEN")
        return MeddraChain(
            verbatim=verbatim,
            llt=key,
            llt_code=crosswalk.meddra_term_code("LLT", key),
            pt=None,
            soc=SOC.get(soc_code),
            soc_code=soc_code,
            cui=crosswalk.cui_for("event", key),
            matched=False,
            match_method="unmatched",
            confidence=0.0,
            audit=audit,
        )

    pt = chain.get("pt")
    soc_code = chain.get("soc_code") or "GEN"
    row = crosswalk.crosswalk_row("event", pt or key)

    return MeddraChain(
        verbatim=verbatim,
        llt=llt,
        llt_code=crosswalk.meddra_term_code("LLT", llt),
        pt=pt,
        pt_code=row.get("meddra_pt_code"),
        hlt=chain.get("hlt"),
        hlt_code=crosswalk.meddra_term_code("HLT", chain.get("hlt") or ""),
        hlgt=chain.get("hlgt"),
        hlgt_code=crosswalk.meddra_term_code("HLGT", chain.get("hlgt") or ""),
        soc=SOC.get(soc_code, SOC["GEN"]),
        soc_code=soc_code,
        soc_term_code=crosswalk.meddra_term_code("SOC", SOC.get(soc_code, "")),
        cui=row.get("cui"),
        snomed_ct=row.get("snomed_ct"),
        oae=row.get("oae"),
        icd11=_icd11(pt) if online else None,
        matched=True,
        match_method=method,
        confidence=confidence,
        audit=audit,
    )


def _icd11(pt: Optional[str]) -> Optional[str]:
    if not pt:
        return None
    try:
        from ..meddra import icd11_code  # noqa: PLC0415 - optional, credential gated

        return icd11_code(pt)
    except Exception:
        return None


def hierarchy_snapshot(soc_code: Optional[str] = None) -> List[dict]:
    """Nested SOC → HLGT → HLT → PT projection for the tree playground."""
    _build_index()
    socs: Dict[str, dict] = {}
    for chain in _PT_INDEX.values():
        code = chain.get("soc_code") or "GEN"
        if soc_code and code != soc_code:
            continue
        soc_node = socs.setdefault(code, {
            "level": "SOC",
            "code": code,
            "name": SOC.get(code, SOC["GEN"]),
            "term_code": crosswalk.meddra_term_code("SOC", SOC.get(code, "")),
            "children": {},
        })
        hlgt_name = chain.get("hlgt") or "Unclassified group"
        hlgt_node = soc_node["children"].setdefault(hlgt_name, {
            "level": "HLGT",
            "name": hlgt_name,
            "term_code": crosswalk.meddra_term_code("HLGT", hlgt_name),
            "children": {},
        })
        hlt_name = chain.get("hlt") or "Unclassified term group"
        hlt_node = hlgt_node["children"].setdefault(hlt_name, {
            "level": "HLT",
            "name": hlt_name,
            "term_code": crosswalk.meddra_term_code("HLT", hlt_name),
            "children": [],
        })
        hlt_node["children"].append({
            "level": "PT",
            "name": chain.get("pt"),
            "term_code": crosswalk.meddra_term_code("PT", chain.get("pt") or ""),
            "llts": chain.get("llts") or [],
        })

    def _flatten(node: dict) -> dict:
        children = node.get("children")
        if isinstance(children, dict):
            node = {**node, "children": [_flatten(c) for c in children.values()]}
        return node

    return sorted((_flatten(n) for n in socs.values()), key=lambda n: n["name"])


def known_pt_count() -> int:
    _build_index()
    return len(_PT_INDEX)
