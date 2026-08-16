"""VigilAI FastAPI application factory (Phase 4 entrypoint).

Initializes the async app, CORS for the React/Vite frontend, router mounts,
and ``async_sessionmaker`` dependency injection used by Omni-Search + PRR/ROR
routes. Preserves auth RBAC, project scoping, and legacy ``/api`` surfaces.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agentic.routes import router as agentic_router
from .api.auth_routes import router as auth_router
from .api.deps import dispose_async_engine, init_async_engine
from .api.routes import api_v1_router, router
from .auth import decode_token
from .biotech_homepage.routes import router as biotech_router
from .config import settings
from .database import SessionLocal, init_db
from .forge.routes import router as forge_router
from .llm import status as llm_status
from .models import User
from .projects.routes import router as projects_router
from .projects.scope import reset_request_project_id, set_request_project_id
from .rbac import min_role_for_write, role_rank

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("vigilai.main")

# Local Vite / CRA + production Vercel origins
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "https://vigil-ai-eight.vercel.app",
    "https://vigil-ai.vercel.app",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: sync schema seed + async engine. Shutdown: dispose pools."""
    init_db()
    from .auth import seed_admin
    from .projects.seed import ensure_projects

    db = SessionLocal()
    try:
        seed_admin(db)
        ensure_projects(db)
    finally:
        db.close()

    try:
        init_async_engine()
        LOGGER.info("Async session factory initialized")
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Async engine deferred until first request: %s", exc)

    yield

    await dispose_async_engine()
    from .database import checkpoint_wal

    checkpoint_wal()


def create_app() -> FastAPI:
    """Application factory — used by uvicorn ``app.main:app`` and tests."""
    application = FastAPI(
        title="VigilAI",
        description=(
            "Real-Time Social Listening for Patient Experience & Safety Signals "
            "(worldwide) — OMOP CDM v5.4 + Omni-Search disproportionality API"
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        # Reflect request Origin when credentials are used — browsers reject ACAO:* + credentials.
        allow_origins=CORS_ORIGINS,
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def _enforce_rbac(request: Request, call_next):
        """Viewer = read-only API; analyst = ops writes; admin = users + reset."""
        needed = min_role_for_write(request.url.path, request.method)
        if needed is None:
            return await call_next(request)

        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        payload = decode_token(auth[7:].strip())
        if not payload:
            return JSONResponse({"detail": "invalid or expired token"}, status_code=401)

        db = SessionLocal()
        try:
            user = db.get(User, payload.get("uid"))
            if user is None or not user.is_active:
                return JSONResponse({"detail": "authentication required"}, status_code=401)
            if role_rank(user.role) < role_rank(needed):
                return JSONResponse({"detail": f"requires {needed} role"}, status_code=403)
        finally:
            db.close()

        return await call_next(request)

    @application.middleware("http")
    async def _bind_project_context(request: Request, call_next):
        """Propagate X-Project-Id into ingest/recompute so Fetch lands in the active workspace."""
        raw = request.headers.get("X-Project-Id") or request.query_params.get("project_id")
        pid = None
        if raw is not None and str(raw).strip():
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                pid = None
        token = set_request_project_id(pid)
        try:
            return await call_next(request)
        finally:
            reset_request_project_id(token)

    # Legacy /api + Phase 4 /api/v1 (signals router included via api_v1_router)
    application.include_router(router)
    application.include_router(api_v1_router)
    application.include_router(auth_router)
    application.include_router(forge_router)
    application.include_router(agentic_router)
    application.include_router(projects_router)
    application.include_router(biotech_router)

    @application.get("/api/health")
    async def health() -> dict:
        from .nlp.transformer_ner import available as ner_available
        from .projects.capabilities import pipeline_capabilities

        llm = llm_status()
        return {
            "status": "ok",
            "service": "VigilAI",
            "version": "1.0.0",
            "scope": "worldwide",
            "llm_enabled": settings.llm_enabled,
            "llm": llm,
            "llm_backend": llm.get("backend", "unknown"),
            "transformer_ner": ner_available(),
            "presidio": settings.use_presidio,
            "pipeline_capabilities": pipeline_capabilities(),
            "phase4_signals": True,
        }

    @application.get("/")
    async def root() -> dict:
        return {
            "service": "VigilAI",
            "docs": "/docs",
            "health": "/api/health",
            "signals": "/api/v1/signals/{query}",
        }

    return application


# Uvicorn / Render entry: ``uvicorn app.main:app``
app = create_app()
