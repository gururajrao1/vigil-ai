"""Enterprise ontology mapping engine: hierarchy, chemistry, devices, SOC roll-up."""
from __future__ import annotations

import pytest

from app.config import settings
from app.nlp.ontology import clear_cache
from app.nlp.ontology_engine import (
    device_mapper,
    dictionary_store,
    drug_chemical_mapper,
    engine_status,
    map_verbatim_to_full_ontology,
    meddra_mapper,
)


@pytest.fixture(autouse=True)
def _offline_only(monkeypatch):
    """Nothing in the engine may depend on a network call."""
    monkeypatch.setattr(settings, "use_rxnorm", False, raising=False)
    monkeypatch.setattr(settings, "use_chebi", False, raising=False)
    clear_cache()
    yield
    clear_cache()


# --------------------------------------------------------------------------- #
# MedDRA hierarchy
# --------------------------------------------------------------------------- #
def test_patient_wording_resolves_full_five_tier_chain():
    chain = meddra_mapper.map_event("racing heart")
    assert chain.matched
    assert chain.pt == "Palpitations"
    assert chain.hlt and chain.hlgt
    assert chain.soc == "Cardiac disorders"
    assert chain.cui and chain.cui.startswith("CUI-SUR-")
    assert chain.snomed_ct and chain.oae
    assert [t["level"] for t in chain.tiers()] == ["SOC", "HLGT", "HLT", "PT", "LLT"]


def test_free_text_phrase_matches_by_token_subset():
    chain = meddra_mapper.map_event("my heart keeps racing")
    assert chain.matched
    assert chain.pt == "Palpitations"
    assert chain.match_method in {"llt_substring", "llt_token_subset"}
    assert chain.confidence < 0.95


def test_unmatched_event_is_reported_honestly():
    chain = meddra_mapper.map_event("banana bread")
    assert not chain.matched
    assert chain.pt is None
    assert chain.verbatim == "banana bread"


def test_chain_soc_agrees_with_stored_surrogate_coding():
    from app.nlp.meddra import map_term

    for verbatim in ("nausea", "rash", "fatigue", "myocarditis", "miscarriage"):
        chain = meddra_mapper.map_event(verbatim)
        assert chain.soc_code == map_term(verbatim)["soc_code"]


def test_hierarchy_snapshot_nests_soc_to_pt():
    tree = meddra_mapper.hierarchy_snapshot("CARD")
    assert tree and tree[0]["level"] == "SOC"
    hlgt = tree[0]["children"][0]
    assert hlgt["level"] == "HLGT"
    assert hlgt["children"][0]["level"] == "HLT"
    assert hlgt["children"][0]["children"][0]["level"] == "PT"


# --------------------------------------------------------------------------- #
# Drug + chemistry
# --------------------------------------------------------------------------- #
def test_brand_maps_to_ingredient_atc_ladder_and_chebi():
    mapped = drug_chemical_mapper.map_drug("Ozempic")
    assert mapped.matched
    assert mapped.preferred_generic == "semaglutide"
    assert mapped.atc_code == "A10BJ06"
    assert [lvl.level for lvl in mapped.atc_levels] == [1, 2, 3, 4, 5]
    assert mapped.atc_levels[0].label == "Alimentary tract and metabolism"
    assert mapped.chemical and mapped.chemical.chebi_id == "CHEBI:167574"
    assert mapped.rxnorm_id.startswith("RXNORM:")


def test_small_molecule_carries_smiles_and_similarity():
    mapped = drug_chemical_mapper.map_drug("isotretinoin")
    assert mapped.chemical.chebi_id == "CHEBI:6067"
    assert mapped.chemical.smiles
    score, method = drug_chemical_mapper.tanimoto(
        mapped.chemical.smiles, mapped.chemical.smiles
    )
    assert score == 1.0
    assert method in {"rdkit_morgan_ecfp4", "smiles_ngram_surrogate"}


def test_structural_neighbours_rank_within_the_chebi_subset():
    neighbours = drug_chemical_mapper.similar_drugs("ibuprofen")
    assert neighbours
    assert neighbours[0].tanimoto >= neighbours[-1].tanimoto
    assert all(n.generic != "ibuprofen" for n in neighbours)


def test_atc_class_members_share_the_prefix():
    members = drug_chemical_mapper.atc_class_members("C10AA")
    assert "atorvastatin" in members and "simvastatin" in members


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
def test_device_maps_to_gmdn_emdn_and_risk_class():
    mapped = device_mapper.map_device("pacemaker", "lead dislodgement")
    assert mapped.matched
    assert mapped.gmdn_code == "GMDN-35141"
    assert mapped.emdn_code == "EMDN-J0101"
    assert mapped.fda_class == "III" and mapped.eu_mdr_class == "III"
    assert mapped.implantable and not mapped.is_samd
    assert mapped.imdrf_code == "IMDRF-A1504"


def test_brand_name_and_fda_product_code_both_resolve():
    assert device_mapper.map_device("dexcom").canonical_device == "continuous glucose monitor"
    assert device_mapper.map_device("LZG").canonical_device == "insulin pump"


def test_software_as_medical_device_is_flagged():
    mapped = device_mapper.map_device("hybrid closed loop")
    assert mapped.matched and mapped.is_samd
    assert mapped.eu_mdr_class == "IIb"


# --------------------------------------------------------------------------- #
# Facade
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "verbatim,expected",
    [("racing heart", "event"), ("Ozempic", "drug"), ("pacemaker", "device")],
)
def test_facade_detects_entity_type(verbatim, expected):
    mapped = map_verbatim_to_full_ontology(verbatim)
    assert mapped.resolved_entity_type == expected
    assert mapped.audit.is_surrogate is True
    assert mapped.audit.online_enrichment is False
    assert mapped.verbatim == verbatim


def test_facade_payload_has_required_keys_for_mcp():
    payload = map_verbatim_to_full_ontology("pacemaker", failure_mode="battery failure").model_dump()
    for key in ("verbatim", "resolved_entity_type", "cui", "codes", "audit", "notes"):
        assert key in payload
    assert payload["codes"]["gmdn"] == "GMDN-35141"
    assert payload["device"]["imdrf_code"] == "IMDRF-A1201"


def test_engine_status_reports_loaded_surrogates():
    status = engine_status()
    assert status["is_surrogate"] is True
    assert status["counts"]["meddra_chains"] > 20
    assert "meddra_hierarchy_surrogate.json" in status["loaded_files"]


def test_dictionary_store_falls_back_when_artifact_missing(monkeypatch):
    monkeypatch.setattr(dictionary_store, "_CACHE", {}, raising=False)
    monkeypatch.setattr(dictionary_store, "_load_file", lambda stem: {})
    chains = dictionary_store.meddra_chains()
    assert chains, "embedded PT/SOC fallback must still produce chains"
    assert any(c["pt"] == "Palpitations" for c in chains)
    dictionary_store.clear_cache()


# --------------------------------------------------------------------------- #
# SOC roll-up
# --------------------------------------------------------------------------- #
class _FakeSignal:
    def __init__(self, drug, symptom, count, pt=None, soc=None):
        self.drug = drug
        self.symptom = symptom
        self.post_count = count
        self.meddra_pt = pt
        self.meddra_soc = soc
        self.id = id(self)
        self.product_type = "drug"
        self.device_gmdn = None
        self.strength = "WEAK"
        self.prr = 1.0
        self.eb05 = 0.1
        self.ic025 = -1.0
        self.sdr_flag = False
        self.severity = "Low"
        self.imdrf_term = None


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def options(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def yield_per(self, *_args):
        return iter(self._rows)

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args):
        return _FakeQuery(self._rows)


def test_soc_rollup_raises_alert_when_member_pts_are_sparse():
    from app.analytics.ontological_disproportionality import (
        compute_ontological_disproportionality,
    )

    rows = [
        _FakeSignal("suspectdrug", "anxiety", 2),
        _FakeSignal("suspectdrug", "insomnia", 2),
        _FakeSignal("suspectdrug", "hallucinations", 2),
        _FakeSignal("suspectdrug", "depression", 2),
    ]
    # Broad comparator corpus so the psychiatric class stands out for suspectdrug.
    for i in range(12):
        rows.append(_FakeSignal(f"comparator{i}", "headache", 8))
        rows.append(_FakeSignal(f"comparator{i}", "nausea", 8))

    out = compute_ontological_disproportionality(_FakeSession(rows))
    assert out["totals"]["pt_pairs"] == len(rows)
    assert out["pt_table"] and out["soc_table"]
    psych = [r for r in out["soc_table"]
             if r["product"] == "suspectdrug" and r["soc"] == "Psychiatric disorders"]
    assert psych, "member PTs must roll up into one organ class"
    assert psych[0]["n_member_pts"] == 4
    assert psych[0]["observed_reports"] == 8
    assert psych[0]["sdr_flag"] is True
    assert all(m["reports"] == 2 for m in psych[0]["members"])


def test_empty_corpus_returns_actionable_verdict():
    from app.analytics.ontological_disproportionality import (
        compute_ontological_disproportionality,
    )

    out = compute_ontological_disproportionality(_FakeSession([]))
    assert out["pt_table"] == [] and out["soc_alerts"] == []
    assert "Ingest" in out["verdict"]


def test_hetero_graph_uses_typed_relations():
    from app.graph.knowledge_graph import build_ontology_graph

    rows = [
        _FakeSignal("atorvastatin", "muscle pain", 5),
        _FakeSignal("simvastatin", "muscle pain", 4),
    ]
    graph = build_ontology_graph(_FakeSession(rows))
    relations = set(graph["stats"]["edges_by_relation"])
    assert {"CAUSES_EVENT", "HAS_ATC_CLASS", "BELONGS_TO"} <= relations
    node_types = graph["stats"]["nodes_by_type"]
    assert node_types["drug"] == 2
    assert node_types["meddra_pt"] == 1
    assert "atc" in node_types and "chebi" in node_types
    assert graph["stats"]["pyg_available"] in (True, False)
