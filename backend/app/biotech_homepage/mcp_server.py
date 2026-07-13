"""FastMCP server — ``render_biotech_homepage`` for LLM layout orchestration.

Run::

    cd backend
    python -m app.biotech_homepage.mcp_server
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("vigilai.biotech_homepage.mcp")


def render_biotech_homepage_tool(focus_drug: Optional[str] = None) -> dict[str, Any]:
    from ..database import SessionLocal
    from .layout_engine import render_biotech_homepage

    db = SessionLocal()
    try:
        return render_biotech_homepage(db, focus_drug)
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
        "vigilai-biotech-homepage",
        instructions=(
            "VigilAI biotech product homepage orchestrator. Call "
            "render_biotech_homepage to obtain schema_version="
            "vigilai.biotech_homepage.v1. SPA paints via GET "
            "/api/biotech/homepage. Never claim live VigiBase/Sentinel."
        ),
    )

    @mcp.tool()
    def render_biotech_homepage(focus_drug: str | None = None) -> str:
        """Emit an editorial Life Sciences homepage layout JSON.

        Args:
            focus_drug: Optional product to spotlight (e.g. pregabalin).

        Returns:
            JSON string of BiotechHomepageLayout (hero, pillars, spotlight, …).
        """
        return json.dumps(
            render_biotech_homepage_tool(focus_drug),
            ensure_ascii=False,
        )

    return mcp


def main() -> None:
    mcp = _build_mcp()
    logger.info("Starting VigilAI biotech homepage MCP (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
