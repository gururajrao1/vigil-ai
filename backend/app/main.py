"""VigilAI FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agentic.routes import router as agentic_router
from .api.auth_routes import router as auth_router
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

app = FastAPI(
    title="VigilAI",
    description="Real-Time Social Listening for Patient Experience & Safety Signals (worldwide)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # Reflect request Origin when credentials are used — browsers reject ACAO:* + credentials.
    # Explicit list covers local Vite + production Vercel; "*" alone is unsafe with credentials.
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "https://vigil-ai-eight.vercel.app",
        "https://vigil-ai.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
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


@app.middleware("http")
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


app.include_router(router)
app.include_router(api_v1_router)
app.include_router(auth_router)
app.include_router(forge_router)
app.include_router(agentic_router)
app.include_router(projects_router)
app.include_router(biotech_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    from .auth import seed_admin
    from .projects.seed import ensure_projects

    db = SessionLocal()
    try:
        seed_admin(db)
        ensure_projects(db)
    finally:
        db.close()


@app.on_event("shutdown")
def _shutdown() -> None:
    """Checkpoint WAL on clean shutdown so data is flushed to the main DB file."""
    from .database import checkpoint_wal
    checkpoint_wal()


@app.get("/api/health")
def health() -> dict:
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
    }


@app.get("/")
def root() -> dict:
    return {"service": "VigilAI", "docs": "/docs", "health": "/api/health"}
