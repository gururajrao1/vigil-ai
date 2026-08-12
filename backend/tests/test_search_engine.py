"""Omni-Search / brand-to-chemical mapping engine tests."""
from __future__ import annotations

import pytest

from app.config import settings
from app.search_engine import (
    autocomplete,
    engine_status,
    omni_search,
    resolve_brand_to_chemical,
)
from app.search_engine import bel_resolver, extractor, rxnorm_mapper


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(settings, "use_rxnorm", False, raising=False)
    monkeypatch.setattr(settings, "use_chebi", False, raising=False)
    monkeypatch.setattr(settings, "use_transformer_ner", False, raising=False)


def test_janumet_expands_has_ingredient_combo():
    resolved = resolve_brand_to_chemical("Janumet")
    assert resolved.matched
    generics = [i.generic for i in resolved.ingredients]
    assert generics == ["sitagliptin", "metformin"]
    assert resolved.brand_rxcui
    assert "A10BH01" in resolved.atc_classes
    assert "A10BA02" in resolved.atc_classes
    assert resolved.umls_cui


def test_typo_and_international_brands_resolve():
    assert resolve_brand_to_chemical("ozmpic").ingredients[0].generic == "semaglutide"
    acc = resolve_brand_to_chemical("Accutane")
    assert acc.ingredients[0].generic == "isotretinoin"
    assert acc.status == "discontinued"
    assert resolve_brand_to_chemical("Roaccutane").matched


def test_autocomplete_fuzzy_micromesh():
    hits = autocomplete("warfr")
    assert hits and hits[0]["term"] == "warfarin"


def test_extractor_handles_colloquial_ade():
    spans = extractor.extract_spans("took Janumet and felt sick to my stomach")
    kinds = {s.kind for s in spans}
    texts = " ".join(s.text.lower() for s in spans)
    assert "drug" in kinds
    assert "janumet" in texts
    assert "event" in kinds


def test_bel_links_to_cui():
    spans = extractor.extract_spans("warfarin")
    linked = bel_resolver.link_spans(spans)
    assert linked and linked[0].cui and linked[0].cui.startswith("CUI-SUR-")


def test_omni_search_resolution_only():
    out = omni_search("Janumet", include_analytics=False)
    assert out.resolution and out.resolution.matched
    assert len(out.resolution.ingredients) == 2
    assert out.audit.is_surrogate is True


def test_universe_subset_report_structure():
    class _Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    class _DB:
        def query(self, *a, **k):
            return _Q()

    from app.search_engine import omop_analytics

    resolution = resolve_brand_to_chemical("ozempic")
    report = omop_analytics.compute_universe_vs_subset(
        _DB(), resolution, subset_brands=["ozempic"]
    )
    assert report.universe_ingredients == ["semaglutide"]
    assert "Ingest" in report.verdict or "Universe" in report.verdict


def test_mcp_payload_keys():
    payload = resolve_brand_to_chemical("Eliquis").model_dump()
    for key in (
        "query_term", "umls_cui", "ingredient_rxcuis", "ingredients",
        "atc_classes", "brand_rxcui", "matched", "audit",
    ):
        assert key in payload


def test_engine_status_lists_research_grounding():
    status = engine_status()
    assert status["counts"]["rxe_brands"] >= 10
    assert "CADEC" in status["research_grounding"]
