"""Redis cache for Google access tokens, encrypted at rest.

Has to be Redis rather than an in-process dict: ``api``, ``worker``, and
``scheduler`` are separate consumer processes, and the pipeline builds a fresh
integration client for *every* tool call — so a process-local cache would still
multiply refresh traffic, and no cache at all would put a Google round-trip in
front of every single skill invocation.

Values are Fernet-encrypted because the dev compose Redis has no password, and a
cached bearer token is as good as the grant for its lifetime.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import settings
from app.core.logging import logger
from app.core.security import TokenError, decrypt_secret, encrypt_secret

_PREFIX = "google:at:"


def cache_key(tenant_id: uuid.UUID, provider: str) -> str:
    return f"{_PREFIX}{tenant_id}:{provider}"


async def get_cached_access_token(
    redis: Any, tenant_id: uuid.UUID, provider: str
) -> str | None:
    raw = await redis.get(cache_key(tenant_id, provider))
    if raw is None:
        return None
    try:
        return decrypt_secret(raw)
    except (TokenError, ValueError):
        # Fernet key rotated (or a stray plaintext value): treat as a miss rather
        # than failing the tool call, and drop the unusable entry.
        logger.warning("discarding undecryptable cached google access token")
        await redis.delete(cache_key(tenant_id, provider))
        return None


async def cache_access_token(
    redis: Any,
    tenant_id: uuid.UUID,
    provider: str,
    token: str,
    expires_in: int,
) -> None:
    """Cache a token, expiring it early so an in-flight call can't race the expiry."""
    ttl = max(60, expires_in - settings.google_token_cache_skew_seconds)
    await redis.set(cache_key(tenant_id, provider), encrypt_secret(token), ex=ttl)


async def invalidate_access_token(
    redis: Any, tenant_id: uuid.UUID, provider: str
) -> None:
    """Drop the cached token — required on disconnect, or it stays usable for ~an hour."""
    await redis.delete(cache_key(tenant_id, provider))


__all__ = [
    "cache_access_token",
    "cache_key",
    "get_cached_access_token",
    "invalidate_access_token",
]
