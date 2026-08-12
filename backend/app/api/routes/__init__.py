"""VigilAI REST API routers.

``router`` — legacy/unversioned surface (``/api/...``) from ``_core``.
``api_v1_router`` — Module 3+ versioned surface (``/api/v1/...``).
"""
from __future__ import annotations

from fastapi import APIRouter

from ._core import router  # noqa: F401
from .etl import router as etl_router
from .signals import router as signals_v1_router

# Mount ETL under the legacy /api surface
router.include_router(etl_router)

api_v1_router = APIRouter()
api_v1_router.include_router(signals_v1_router, prefix="/api/v1")

__all__ = ["router", "api_v1_router", "signals_v1_router", "etl_router"]
