"""DATABASE_URL normalization for asyncpg vs psycopg2."""
from __future__ import annotations

from app.db.pg_url import asyncpg_connect_args, create_async_engine_kwargs, normalize_database_url


def test_async_strips_sslmode_and_uses_connect_args():
    raw = "postgresql://u:p@ep-cool.neon.tech/neondb?sslmode=require"
    normalized = normalize_database_url(raw, is_async=True)
    assert "asyncpg" in normalized
    assert "sslmode" not in normalized.lower()
    args = asyncpg_connect_args(normalized, original_url=raw)
    assert args.get("ssl") is True
    url, kwargs = create_async_engine_kwargs(raw)
    assert "sslmode" not in url.lower()
    assert kwargs["connect_args"]["ssl"] is True


def test_sync_preserves_sslmode():
    raw = "postgresql://u:p@ep-cool.neon.tech/neondb?sslmode=require"
    sync_url = normalize_database_url(raw, is_async=False)
    assert "sslmode=require" in sync_url
    assert "asyncpg" not in sync_url


def test_local_async_no_ssl_by_default():
    raw = "postgresql://vigilai:vigilai@127.0.0.1:5432/vigilai"
    normalized = normalize_database_url(raw, is_async=True)
    args = asyncpg_connect_args(normalized, original_url=raw)
    assert args == {}


def test_local_async_honors_explicit_sslmode():
    raw = "postgresql://vigilai:vigilai@localhost:5432/vigilai?sslmode=require"
    normalized = normalize_database_url(raw, is_async=True)
    assert "sslmode" not in normalized.lower()
    args = asyncpg_connect_args(normalized, original_url=raw)
    assert args.get("ssl") is True
