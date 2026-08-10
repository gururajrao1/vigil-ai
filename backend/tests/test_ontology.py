"""Product ontology layer: brand ↔ generic (INN dual) ↔ chemical expansion."""
from __future__ import annotations

import pytest

from app.config import settings
from app.nlp.ontology import (
    aliases_for_product,
    clear_cache,
    expand_product,
    preferred_generic,
    resolve_product,
    same_concept,
)


@pytest.fixture(autouse=True)
def _offline_only(monkeypatch):
    """No test may depend on RxNorm/ChEBI being reachable."""
    monkeypatch.setattr(settings, "use_rxnorm", False, raising=False)
    monkeypatch.setattr(settings, "use_chebi", False, raising=False)
    clear_cache()
    yield
    clear_cache()


def test_brand_resolves_to_preferred_generic():
    concept = resolve_product("Tylenol")
    assert concept.preferred_generic == "paracetamol"
    assert concept.atc == "N02BE01"
    assert concept.concept_id.startswith("VIG-PC-")


def test_inn_duals_share_one_concept():
    assert preferred_generic("acetaminophen") == "paracetamol"
    assert preferred_generic("albuterol") == "salbutamol"
    assert resolve_product("acetaminophen").concept_id == resolve_product("paracetamol").concept_id
    assert same_concept("tylenol", "acetaminophen")
    assert not same_concept("tylenol", "advil")


def test_expand_returns_all_three_naming_tiers():
    out = expand_product("advil")
    tiers = out["tiers"]
    assert out["preferred_generic"] == "ibuprofen"
    assert "advil" in tiers["brand"] and "brufen" in tiers["brand"]
    assert "ibuprofen" in tiers["generic"]
    assert any("propanoic acid" in c for c in tiers["chemical"])


def test_alias_closure_pools_brand_and_generic():
    aliases = aliases_for_product("dolo 650")
    assert {"paracetamol", "acetaminophen", "tylenol", "crocin"} <= aliases


def test_unknown_product_degrades_without_network():
    concept = resolve_product("zzq-experimental-agent")
    assert concept.preferred_generic == "zzq-experimental-agent"
    assert concept.rxcui is None
    assert concept.chemicals == []


def test_empty_surface_is_safe():
    concept = resolve_product("")
    assert concept.preferred_generic == ""
    assert aliases_for_product("") == frozenset()
    assert not same_concept("", "paracetamol")
