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
        return url.render_as_string(hide_password=False)
    if driver in {"postgresql", "postgres", "postgresql+psycopg2", "postgresql+psycopg"}:
        return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)
    if driver.startswith("sqlite"):
        if "aiosqlite" not in driver:
            return url.set(drivername="sqlite+aiosqlite").render_as_string(hide_password=False)
        return url.render_as_string(hide_password=False)
    raise ValueError(f"Unsupported DATABASE_URL dialect for async sessions: {driver!r}")


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
    kwargs: dict = {"pool_pre_ping": True}
    if not async_url.startswith("sqlite"):
        kwargs.update(pool_size=5, max_overflow=10, pool_recycle=280)

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


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an ``AsyncSession`` per request."""
    factory = init_async_engine()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
