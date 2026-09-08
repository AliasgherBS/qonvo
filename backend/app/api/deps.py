"""FastAPI dependencies: auth, tenant-scoped DB sessions, Redis/arq handles."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from arq import ArqRedis
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenClaims, TokenError, decode_jwt
from app.core.tenancy import system_session, tenant_session


def get_claims(authorization: str | None = Header(default=None)) -> TokenClaims:
    """Decode and verify the bearer JWT (DESIGN.md §8)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        return decode_jwt(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_tenant(claims: TokenClaims = Depends(get_claims)) -> UUID:
    """Resolve the tenant the request acts on (must be present in the token)."""
    if claims.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="token carries no tenant_id",
        )
    return claims.tenant_id


def require_owner(claims: TokenClaims = Depends(get_claims)) -> UUID:
    """Tenant present AND the caller holds the ``owner`` role.

    **What a staff seat may do**, decided deliberately rather than by which
    dependency a route happened to pick:

    * Read and reply in the inbox, take over and release a conversation.
    * Read and add knowledge. Deleting is owner-only: a source removed is
      grounding the rep silently loses.
    * Read analytics, usage, the plan and the config.
    * Mark their own notifications read.

    And may not: anything that moves money, ends service, changes what the rep
    tells customers, or re-links the number. That list is not arbitrary. Before
    this was enforced, ``PUT /api/config`` accepted ``payment_details``, the
    free text the ``share_payment_details`` skill reads out verbatim, so a
    receptionist could substitute their own account number and the business's
    own WhatsApp number would tell its customers to pay it, with nothing on any
    screen showing that it happened.

    The product already promised this: the Team page reads "Owners manage the
    team and billing."
    """
    tenant_id = require_tenant(claims)
    if claims.role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner role required")
    return tenant_id


async def get_db(tenant_id: UUID = Depends(require_tenant)) -> AsyncIterator[AsyncSession]:
    """Yield a tenant-scoped session (RLS enforced via ``app.tenant_id``)."""
    async with tenant_session(tenant_id) as session:
        yield session


def require_admin(claims: TokenClaims = Depends(get_claims)) -> TokenClaims:
    """Gate ``/api/admin/*`` routes to the cross-tenant ``qonvo_admin`` flag (§8, §9)."""
    if not claims.is_qonvo_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="qonvo_admin required")
    return claims


async def get_system_db() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for auth lookups and ``/api/admin/*`` routes.

    Connects as the ``qonvo_system`` BYPASSRLS role (DESIGN.md §3) — the only
    trusted cross-tenant path in the API layer, mirroring webhook tenant
    resolution and scheduler fleet scans.
    """
    async with system_session() as session:
        yield session


def get_arq(request: Request) -> ArqRedis:
    pool: ArqRedis | None = getattr(request.app.state, "arq", None)
    if pool is None:  # pragma: no cover - misconfiguration guard
        raise HTTPException(status_code=503, detail="job queue unavailable")
    return pool


def get_waha(request: Request):
    """Return the shared WAHA client created in the app lifespan."""
    from app.waha.client import WahaClient

    waha: WahaClient | None = getattr(request.app.state, "waha", None)
    if waha is None:  # pragma: no cover - misconfiguration guard
        raise HTTPException(status_code=503, detail="WAHA client unavailable")
    return waha


def get_send_gateway(request: Request):
    """Build a send gateway over the shared WAHA client (never call WahaClient
    send methods directly from route code — DESIGN.md §5.6)."""
    from app.core.redis import get_redis
    from app.waha.send_gateway import SendGateway

    return SendGateway(get_waha(request), get_redis())


def get_redis_dep():
    """Redis as a dependency so route tests can override it with a fake."""
    from app.core.redis import get_redis

    return get_redis()
