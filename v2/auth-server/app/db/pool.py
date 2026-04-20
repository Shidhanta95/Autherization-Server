"""
Async PostgreSQL connection pool using asyncpg.

Managed via FastAPI lifespan — created on startup, closed on shutdown.
"""

import asyncpg

from app.core.config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Create the connection pool. Called once during app startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        min_size=settings.POSTGRES_MIN_POOL,
        max_size=settings.POSTGRES_MAX_POOL,
        server_settings={"search_path": "authz,public"},
    )
    return _pool


async def close_pool() -> None:
    """Close the connection pool. Called during app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Get the current connection pool. Raises if not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool not initialised — call init_pool() first")
    return _pool
