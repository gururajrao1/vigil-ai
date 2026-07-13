"""Role capabilities for VigilAI RBAC (admin > analyst > viewer)."""
from __future__ import annotations

# Hierarchy levels — keep in sync with auth.ROLES
ROLE_LEVEL = {"admin": 3, "analyst": 2, "viewer": 1}

# Mutating API prefixes that require at least analyst (ingest, triage, forge, …).
ANALYST_WRITE_PREFIXES = (
    "/api/ingest/",
    "/api/recompute",
    "/api/stream/",
    "/api/scheduler/",
    "/api/demo/",
    "/api/prewarm",
    "/api/normalize/",
    "/api/forge/",
    "/api/agentic/",
    "/api/projects",
    "/api/alerts/",
    "/api/signals/",
)

# Destructive / tenancy controls — admin only.
ADMIN_WRITE_EXACT = {
    "/api/reset",
}
ADMIN_WRITE_PREFIXES = (
    "/api/auth/users",
)


def role_rank(role: str | None) -> int:
    return ROLE_LEVEL.get((role or "").lower(), 0)


def min_role_for_write(path: str, method: str) -> str | None:
    """Return required min role for a mutating request, or None if unrestricted."""
    m = method.upper()
    if m in ("GET", "HEAD", "OPTIONS"):
        return None
    # Public auth
    if path in ("/api/auth/login", "/api/auth/register"):
        return None
    if path in ADMIN_WRITE_EXACT:
        return "admin"
    for p in ADMIN_WRITE_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return "admin"
    for p in ANALYST_WRITE_PREFIXES:
        if path == p or path.startswith(p):
            # Signal detail GETs are fine; POST narrative/review need analyst
            if path.startswith("/api/signals/") and m == "GET":
                return None
            return "analyst"
    # Default: other POST/PATCH/PUT/DELETE under /api need analyst
    if path.startswith("/api/"):
        return "analyst"
    return None
