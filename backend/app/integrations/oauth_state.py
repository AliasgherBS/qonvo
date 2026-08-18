"""Single-use CSRF state for the Google OAuth round-trip, held in Redis.

The state is an opaque random token, not a signed JWT. Unguessable plus
single-use is exactly the property needed, and a signed token would *still* need
a Redis nonce to be single-use — so it would be strictly more machinery for the
same guarantee. Consumption uses ``GETDEL`` so the read and the delete are atomic
and a replayed callback finds nothing.

This is also what lets the callback resolve its tenant safely: the state was
minted inside an authenticated ``require_tenant`` request, so the tenant id it
carries is trustworthy even though the callback itself arrives with no bearer
token.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import logger

_PREFIX = "oauth:state:"


def state_key(token: str) -> str:
    return f"{_PREFIX}{token}"


@dataclass(frozen=True, slots=True)
class OAuthState:
    tenant_id: uuid.UUID
    provider: str
    return_to: str | None = None


async def issue_state(
    redis: Any,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    return_to: str | None = None,
) -> str:
    """Mint and store a state token; returns the token to put in the authorize URL."""
    token = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"tenant_id": str(tenant_id), "provider": provider, "return_to": return_to}
    )
    await redis.set(
        state_key(token), payload, ex=settings.google_oauth_state_ttl_seconds
    )
    return token


async def consume_state(redis: Any, token: str) -> OAuthState | None:
    """Atomically read-and-delete a state token. ``None`` if unknown or replayed."""
    if not token:
        return None
    raw = await redis.getdel(state_key(token))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return OAuthState(
            tenant_id=uuid.UUID(data["tenant_id"]),
            provider=data["provider"],
            return_to=data.get("return_to"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(f"discarding unparseable oauth state: {exc}")
        return None


__all__ = ["OAuthState", "consume_state", "issue_state", "state_key"]
