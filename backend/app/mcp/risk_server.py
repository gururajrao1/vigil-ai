"""FastMCP tools for VigilAI proactive risk stratification.

Run::

    cd backend
    python -m app.mcp.risk_server
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("vigilai.mcp.risk")


def predict_high_risk_populations_impl(
    product_id: str,
    target_ae_pt: str,
    min_confidence: float = 0.80,
    project_id: Optional[int] = None,
) -> dict:
    from ..analytics.risk_strata import predict_high_risk_populations
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        return predict_high_risk_populations(
            db,
            product_id=product_id,
            target_ae_pt=target_ae_pt,
            min_confidence=min_confidence,
            project_id=project_id,
        )
    finally:
        db.close()


def rank_high_risk_populations_impl(
    product_id: str,
    target_ae_pt: str,
    top_n: int = 5,
    project_id: Optional[int] = None,
) -> dict:
    from ..analytics.risk_ranking import rank_high_risk_populations
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        return rank_high_risk_populations(
            db,
            product_id=product_id,
            target_ae_pt=target_ae_pt,
            top_n=top_n,
            project_id=project_id,
        )
    finally:
        db.close()


def get_normalized_feature_matrix_impl(
    product_id: str = "",
    target_ae_pt: str = "",
    project_id: Optional[int] = None,
    include_explainability: bool = True,
) -> dict:
    """Phase-2 feature store entry for FastMCP / API."""
    from ..analytics.feature_store import get_normalized_feature_matrix
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        return get_normalized_feature_matrix(
            db,
            product_id=product_id or None,
            target_ae_pt=target_ae_pt or None,
            project_id=project_id,
            include_explainability=include_explainability,
        )
    finally:
        db.close()


def evaluate_narrative_causality_impl(
    text: str,
    product: str = "",
    event: str = "",
    fda_known: bool = False,
) -> dict:
    from ..nlp.causality_engine import evaluate_narrative_causality

    return evaluate_narrative_causality(
        text,
        product=product,
        event=event,
        fda_known=fda_known,
    )


def _build_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        try:
            from fastmcp import FastMCP
        except ImportError as exc:
            raise SystemExit(
                "MCP SDK not installed. pip install 'mcp[cli]' "
                f"(or fastmcp). Underlying: {exc}"
            ) from exc

    mcp = FastMCP(
        "vigilai-risk-strata",
        instructions=(
            "VigilAI proactive risk stratification, ranking, feature store, and "
            "narrative causality (WHO-UMC + Naranjo). Offline-first; "
            "not for clinical decisions."
        ),
    )

    @mcp.tool()
    async def evaluate_narrative_causality(
        text: str,
        product: str = "",
        event: str = "",
        fda_known: bool = False,
    ) -> str:
        """Run WHO-UMC + Naranjo causality assessment over a case narrative.

        Args:
            text: Case / social narrative.
            product: Suspected product name.
            event: MedDRA-style Preferred Term / symptom.
            fda_known: Whether openFDA already lists the pair.

        Returns:
            JSON with who_umc, naranjo checklist, and de/rechallenge tags.
        """
        out = evaluate_narrative_causality_impl(
            text=text,
            product=product,
            event=event,
            fda_known=fda_known,
        )
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    async def predict_high_risk_populations(
        product_id: str,
        target_ae_pt: str,
        min_confidence: float = 0.80,
    ) -> str:
        """Analyze historical corpus data to identify high-risk patient
        demographic and comorbidity segments for a given product–AE pair.

        Args:
            product_id: Drug, vaccine, or device name (e.g. 'catheter', 'lithium').
            target_ae_pt: MedDRA-style Preferred Term / event (e.g. 'necrosis').
            min_confidence: Minimum predicted risk score threshold (default 0.80).

        Returns:
            JSON string with segments, predicted_risk_score,
            relative_risk_elevation, and top_contributing_factors.
        """
        out = predict_high_risk_populations_impl(
            product_id=product_id,
            target_ae_pt=target_ae_pt,
            min_confidence=min_confidence,
        )
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    async def rank_high_risk_populations(
        product_id: str,
        target_ae_pt: str,
        top_n: int = 5,
    ) -> str:
        """Ranks subpopulations by relative risk elevation for a given product-AE pair,
        identifying demographic and comorbidity drivers alongside mitigation rules.

        Args:
            product_id: Drug, vaccine, or device name.
            target_ae_pt: MedDRA-style Preferred Term / event.
            top_n: Maximum ranked strata to return (default 5).

        Returns:
            JSON with Risk Elevation Multiplier ranking, Yates χ² gates,
            feature attribution %, and domain mitigation (labeling vs device RCA).
        """
        out = rank_high_risk_populations_impl(
            product_id=product_id,
            target_ae_pt=target_ae_pt,
            top_n=top_n,
        )
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    async def get_normalized_feature_matrix(
        product_id: str = "",
        target_ae_pt: str = "",
        include_explainability: bool = True,
    ) -> str:
        """Return the VigilAI Product–Event–Cohort feature matrix X with
        PRR/ROR/χ²/EB05/IC025, demographics, comorbidities, polypharmacy,
        GNN degree centrality, and optional 4-gate NLP explainability traces.

        Args:
            product_id: Optional product filter (brand or generic).
            target_ae_pt: Optional MedDRA-style Preferred Term filter.
            include_explainability: Attach sample 4-gate traces (default True).

        Returns:
            JSON with feature_names, matrix rows, dense X, and explainability.
        """
        out = get_normalized_feature_matrix_impl(
            product_id=product_id,
            target_ae_pt=target_ae_pt,
            include_explainability=include_explainability,
        )
        return json.dumps(out, ensure_ascii=False)

    @mcp.tool()
    async def get_pgx_gene_associations(drug_name: str, event: str = "") -> str:
        """Return PharmGKB/CPIC gene-variant warnings and metabolizer profiles.

        Offline-first curated table with optional live API enrichment.
        """
        from ..analytics.pgx_engine import get_pgx_gene_associations as _fn

        return json.dumps(_fn(drug_name, event=event, offline_only=True), ensure_ascii=False)

    @mcp.tool()
    async def evaluate_benefit_risk_ratio(drug_id: str, primary_ae_pt: str) -> str:
        """Return PrOACT-URL balance metrics, efficacy benchmarks, and risk trade-offs."""
        from ..analytics.benefit_risk import evaluate_benefit_risk_ratio as _fn

        return json.dumps(
            _fn(drug_id, primary_ae_pt, offline_only=True),
            ensure_ascii=False,
        )

    @mcp.tool()
    async def get_inspection_lead_time_metrics() -> str:
        """Return SLA compliance metrics, pending reviews, and overdue escalation alerts."""
        from ..database import SessionLocal
        from ..reports.inspection_audit import inspection_portfolio

        db = SessionLocal()
        try:
            return json.dumps(inspection_portfolio(db, limit=200), ensure_ascii=False)
        finally:
            db.close()

    return mcp


def main() -> None:
    mcp = _build_mcp()
    logger.info("Starting VigilAI risk stratification MCP (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
