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
)

from ..db.pg_url import create_async_engine_normalized

LOGGER = logging.getLogger("vigilai.api.deps")

_ENGINE: Optional[AsyncEngine] = None
_SESSION_FACTORY: Optional[async_sessionmaker[AsyncSession]] = None


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

    kwargs: dict = {}
    if not raw.startswith("sqlite"):
        kwargs.update(pool_size=5, max_overflow=10, pool_recycle=280)

    _ENGINE = create_async_engine_normalized(raw, **kwargs)
    _SESSION_FACTORY = async_sessionmaker(
        _ENGINE,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    LOGGER.info(
        "Async SQLAlchemy engine ready (%s)",
        make_url(_ENGINE.url.render_as_string(hide_password=False)).drivername
        if hasattr(_ENGINE.url, "render_as_string")
        else "postgresql+asyncpg",
    )
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
