"""Shared async Redis client (decoded responses)."""

from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings

_pool: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return a lazily-created, process-wide Redis client."""
    global _pool
    if _pool is None:
        _pool = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
