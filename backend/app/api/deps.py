"""FastAPI dependency injection — async SQLAlchemy sessions."""
from __future__ import annotations

import logging
import os
from typing import AsyncGenerator, Optional

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

LOGGER = logging.getLogger("vigilai.api.deps")

_ENGINE: Optional[AsyncEngine] = None
_SESSION_FACTORY: Optional[async_sessionmaker[AsyncSession]] = None


def _to_async_url(raw: str) -> str:
    url = make_url(raw.strip())
    driver = (url.drivername or "").lower()
    if "asyncpg" in driver:
        pass
    elif driver in {"postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"}:
        url = url.set(drivername="postgresql+asyncpg")
    elif driver.startswith("sqlite"):
        if "aiosqlite" not in driver:
            url = url.set(drivername="sqlite+aiosqlite")
    else:
        raise ValueError(f"Unsupported DATABASE_URL dialect for async sessions: {driver!r}")

    # asyncpg does not honor libpq sslmode the same way — drop it; use connect_args
    query = dict(url.query) if url.query else {}
    for key in list(query.keys()):
        if key.lower() in {"sslmode", "ssl", "channel_binding"}:
            query.pop(key, None)
    url = url.set(query=query)
    return url.render_as_string(hide_password=False)


def _connect_args_for(async_url: str) -> dict:
    """Neon / Render / cloud Postgres need TLS; local Docker usually does not."""
    url = make_url(async_url)
    if "asyncpg" not in (url.drivername or "").lower():
        return {}
    host = (url.host or "").lower()
    if host in {"localhost", "127.0.0.1", "::1", ""}:
        return {}
    # True enables default SSL context (works with Neon)
    return {"ssl": True}


def get_database_url() -> str:
    raw = (os.getenv("DATABASE_URL") or "").strip()
    if raw:
        return raw
    from ..config import settings

    return (settings.database_url or "").strip()


def init_async_engine(database_url: Optional[str] = None) -> async_sessionmaker[AsyncSession]:
    """Create (or reuse) the process-wide async engine + session factory."""
    global _ENGINE, _SESSION_FACTORY
    if _SESSION_FACTORY is not None and _ENGINE is not None:
        return _SESSION_FACTORY

    raw = (database_url or get_database_url()).strip()
    if not raw:
        raise RuntimeError("DATABASE_URL is not configured")

    async_url = _to_async_url(raw)
    kwargs: dict = {
        "pool_pre_ping": True,
        "connect_args": _connect_args_for(async_url),
    }
    if not async_url.startswith("sqlite"):
        kwargs.update(pool_size=2, max_overflow=1, pool_recycle=280)

    _ENGINE = create_async_engine(async_url, **kwargs)
    _SESSION_FACTORY = async_sessionmaker(
        _ENGINE,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    LOGGER.info("Async SQLAlchemy engine ready (%s)", make_url(async_url).drivername)
    return _SESSION_FACTORY


async def dispose_async_engine() -> None:
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is not None:
        await _ENGINE.dispose()
    _ENGINE = None
    _SESSION_FACTORY = None


async def get_async_db() -> AsyncGenerator[Optional[AsyncSession], None]:
    """Yield an ``AsyncSession``, or ``None`` if async Postgres is unavailable.

    Neon TLS / cold-start failures must not take down the Signals route — callers
    fall back to sync SessionLocal + offline Omni-Search.
    """
    try:
        factory = init_async_engine()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Async engine init failed — sync fallback: %s", exc)
        yield None
        return

    try:
        async with factory() as session:
            try:
                # Probe connectivity early so handlers can fall back cleanly
                await session.connection()
                yield session
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Async session failed — sync fallback: %s", exc)
                try:
                    await session.rollback()
                except Exception:
                    pass
                yield None
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Async session factory failed — sync fallback: %s", exc)
        yield None
