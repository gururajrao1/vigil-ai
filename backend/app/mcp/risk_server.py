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
            "VigilAI proactive risk stratification. Call "
            "predict_high_risk_populations to identify demographic and "
            "comorbidity segments with elevated predicted risk for a "
            "product–AE pair. Offline-first; not for clinical decisions."
        ),
    )

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

    return mcp


def main() -> None:
    mcp = _build_mcp()
    logger.info("Starting VigilAI risk stratification MCP (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
