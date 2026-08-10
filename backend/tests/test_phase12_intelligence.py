"""Phase 1–2 predictive intelligence: privacy, OMOP, 4-gate, feature store."""
from __future__ import annotations

from app.database import SessionLocal, init_db
from app.nlp.bioie_benchmark import evaluate_corpus
from app.nlp.four_gate_engine import run_four_gates
from app.privacy.hygiene import author_hash, content_hash, hygiene_pipeline, scrub_text


def test_author_hash_is_hmac_not_plaintext():
    h = author_hash("patient_user_42")
    assert h
    assert "patient_user_42" not in h
    assert len(h) == 64
    assert author_hash("patient_user_42") == h  # stable
    assert author_hash("other") != h


def test_content_hash_stable_under_punctuation():
    a = content_hash("Hello!!!", "Nausea after Tylenol.")
    b = content_hash("hello", "nausea after tylenol")
    assert a == b
    assert len(a) == 64


def test_scrub_text_redacts_email_and_phone():
    cleaned, found, tokens = scrub_text(
        "Call me at +1-555-010-9999 or jane.doe@example.com about Accutane",
        use_presidio=False,
    )
    assert "jane.doe@example.com" not in cleaned
    assert "Accutane" in cleaned or "accutane" in cleaned.lower()
    assert found or tokens  # something was flagged


def test_hygiene_pipeline_accepts_unique_record():
    init_db()
    db = SessionLocal()
    try:
        r = hygiene_pipeline(
            {
                "title": "Side effect report",
                "body": "I took ibuprofen and got a rash.",
                "author": "forum_user_abc",
            },
            db=db,
            bump_duplicate=False,
        )
        assert r.action == "accept"
        assert r.author_hash
        assert r.content_hash
        assert "forum_user_abc" != r.author_hash
    finally:
        db.close()


def test_four_gate_engine_flags_negative_ae():
    out = run_four_gates(
        "Started Accutane last month and my mood dropped into depression. Terrible.",
        use_transformer=False,
        discard_near_neutral=True,
    )
    assert "gate_trace" in out
    assert len(out["gate_trace"]) >= 4
    assert out["pipeline"] == "four_gate_engine_v1"
    # Brand should collapse toward isotretinoin concept
    drugs = out["entities"]["drugs"]
    generics = {(d.get("generic") or d.get("normalized") or "").lower() for d in drugs}
    assert any("isotretinoin" in g or "accutane" in g for g in generics) or out["drug_concepts"]


def test_four_gate_discards_near_neutral():
    out = run_four_gates(
        "Isotretinoin is a medication used for acne treatment according to Wikipedia.",
        use_transformer=False,
        discard_near_neutral=True,
    )
    # Neutral encyclopedia-style text should not become an AE
    assert out["ae_flag"] is False


def test_bioie_benchmark_fixture_runs():
    result = evaluate_corpus(corpus="bc5cdr")
    assert result["n_documents"] >= 1
    assert "micro" in result
    assert "f1" in result["micro"]


def test_clinical_notes_adapter_offline():
    from app.ingestion.adapters import ClinicalNotesAdapter

    result = ClinicalNotesAdapter().run(apply_hygiene=True)
    assert result.source == "clinical_notes"
    assert result.posts  # demo note accepted
    assert result.posts[0]["platform"] == "clinical_note"


def test_omop_sync_and_feature_matrix():
    init_db()
    db = SessionLocal()
    try:
        from app.analytics.feature_store import get_normalized_feature_matrix
        from app.db.schemas.omop_mapper import sync_omop_from_corpus

        sync = sync_omop_from_corpus(db, limit=50, ae_only=True)
        assert "persons" in sync
        assert "drug_exposures" in sync

        matrix = get_normalized_feature_matrix(
            db, include_explainability=False
        )
        assert "feature_names" in matrix
        assert "prr_score" in matrix["feature_names"]
        assert "gnn_degree_centrality" in matrix["feature_names"]
        assert "X" in matrix
        assert matrix["method"] == "product_event_cohort_feature_store_v1"
    finally:
        db.close()


def test_mcp_feature_matrix_impl():
    from app.mcp.risk_server import get_normalized_feature_matrix_impl

    out = get_normalized_feature_matrix_impl(include_explainability=False)
    assert "matrix" in out
    assert "feature_names" in out
