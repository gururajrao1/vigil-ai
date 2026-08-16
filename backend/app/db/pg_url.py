"""PostgreSQL URL normalization for sync (libpq) vs async (asyncpg) engines.

Cloud providers (Neon, Supabase, Render, RDS) append ``?sslmode=require``.
``psycopg2`` accepts that libpq flag; ``asyncpg`` rejects it as
``connect() got an unexpected keyword argument 'sslmode'``.

Callers must not edit ``DATABASE_URL`` env vars — always normalize at connect time.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple, Union

from sqlalchemy.engine import URL, make_url

# SSL-related query keys asyncpg does not accept as connect() kwargs
_ASYNCPG_SSL_KEYS = frozenset({
    "sslmode",
    "ssl",
    "channel_binding",
    "gssencmode",
})

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def _as_url(raw: Union[str, URL]) -> URL:
    if isinstance(raw, URL):
        return raw
    return make_url(str(raw).strip())


def _query_dict(url: URL) -> dict[str, Any]:
    q = url.query
    if not q:
        return {}
    # SQLAlchemy may store query as immutabledict of str -> str | tuple
    return {str(k): v for k, v in dict(q).items()}


def _sslmode_requests_tls(sslmode: Optional[str]) -> bool:
    if not sslmode:
        return False
    mode = str(sslmode).strip().lower()
    return mode in {"require", "verify-ca", "verify-full", "prefer", "true", "1"}


def normalize_database_url(url: str, *, is_async: bool = True) -> str:
    """Return a SQLAlchemy URL safe for sync (psycopg2) or async (asyncpg) engines.

    * **Async** — force ``postgresql+asyncpg``, strip ``sslmode`` / related query
      params (TLS is applied via ``connect_args`` from :func:`asyncpg_connect_args`).
    * **Sync** — prefer ``postgresql+psycopg2`` (or bare ``postgresql``), **keep**
      ``sslmode`` and other libpq query params unchanged.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("DATABASE_URL is empty")

    u = _as_url(raw)
    driver = (u.drivername or "").lower()

    if driver.startswith("sqlite"):
        if is_async and "aiosqlite" not in driver:
            u = u.set(drivername="sqlite+aiosqlite")
        return u.render_as_string(hide_password=False)

    if is_async:
        if "asyncpg" not in driver:
            if driver in {
                "postgresql",
                "postgres",
                "postgresql+psycopg2",
                "postgresql+psycopg",
            }:
                u = u.set(drivername="postgresql+asyncpg")
            else:
                raise ValueError(
                    f"Unsupported DATABASE_URL dialect for asyncpg: {driver!r}"
                )
        query = _query_dict(u)
        for key in list(query.keys()):
            if key.lower() in _ASYNCPG_SSL_KEYS:
                query.pop(key, None)
        u = u.set(query=query)
        return u.render_as_string(hide_password=False)

    # Sync path — preserve sslmode for libpq / psycopg2
    if "asyncpg" in driver:
        try:
            import psycopg2  # noqa: F401

            u = u.set(drivername="postgresql+psycopg2")
        except ImportError:
            u = u.set(drivername="postgresql")
    elif driver in {"postgresql", "postgres"}:
        try:
            import psycopg2  # noqa: F401

            u = u.set(drivername="postgresql+psycopg2")
        except ImportError:
            u = u.set(drivername="postgresql")
    return u.render_as_string(hide_password=False)


def asyncpg_connect_args(
    url: str,
    *,
    original_url: Optional[str] = None,
) -> dict[str, Any]:
    """Build ``connect_args`` for ``create_async_engine`` / asyncpg.

    Cloud hosts get ``ssl=True`` when the original URL asked for TLS via
    ``sslmode=require`` (or host is not localhost). Local Docker/Postgres stays
    plain TCP.
    """
    normalized = _as_url(url)
    if "asyncpg" not in (normalized.drivername or "").lower():
        return {}

    source = _as_url(original_url) if original_url else normalized
    # Prefer sslmode from the *original* env URL before stripping
    query = _query_dict(source)
    sslmode = None
    for k, v in query.items():
        if k.lower() == "sslmode":
            sslmode = v if not isinstance(v, (list, tuple)) else (v[0] if v else None)
            break

    host = (normalized.host or "").lower()
    wants_tls = _sslmode_requests_tls(sslmode) if sslmode else False
    if not wants_tls and host not in _LOCAL_HOSTS:
        # Neon/Render pooled URLs almost always need TLS even if sslmode omitted
        wants_tls = True
    if host in _LOCAL_HOSTS:
        wants_tls = _sslmode_requests_tls(sslmode)

    if wants_tls:
        return {"ssl": True}
    return {}


def create_async_engine_kwargs(
    database_url: str,
    **extra: Any,
) -> Tuple[str, dict[str, Any]]:
    """Return ``(normalized_async_url, kwargs)`` for ``create_async_engine``.

    Merges ``connect_args`` (SSL) with any caller ``extra`` kwargs. Caller
    ``connect_args`` are shallow-merged on top of defaults.
    """
    original = database_url
    normalized = normalize_database_url(database_url, is_async=True)
    connect_args = asyncpg_connect_args(normalized, original_url=original)

    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    kwargs.update(extra)
    user_connect = dict(kwargs.pop("connect_args", None) or {})
    merged = {**connect_args, **user_connect}
    if merged:
        kwargs["connect_args"] = merged
    return normalized, kwargs


def create_async_engine_normalized(database_url: str, **extra: Any):
    """Convenience: ``create_async_engine`` with sslmode-safe URL + connect_args."""
    from sqlalchemy.ext.asyncio import create_async_engine

    normalized, kwargs = create_async_engine_kwargs(database_url, **extra)
    return create_async_engine(normalized, **kwargs)


__all__ = [
    "normalize_database_url",
    "asyncpg_connect_args",
    "create_async_engine_kwargs",
    "create_async_engine_normalized",
]
