"""FastAPI dependencies: auth, tenant-scoped DB sessions, Redis/arq handles."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from arq import ArqRedis
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.revocation import is_revoked
from app.core.security import TokenClaims, TokenError, decode_jwt
from app.core.tenancy import system_session, tenant_session


async def get_claims(authorization: str | None = Header(default=None)) -> TokenClaims:
    """Decode and verify the bearer JWT, and check it has not been revoked.

    Async because of the revocation lookup (teardown X6). A validly signed
    token is not enough on its own: signing out, removing a member, suspending
    a tenant and changing a password all have to make an outstanding token stop
    working, and none of them could while this was a pure signature check.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_jwt(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if await is_revoked(get_redis(), claims):
        # Same 401 shape as an invalid signature, deliberately. "This token was
        # revoked" tells whoever is holding it something they do not need to
        # know, and the client's job is identical either way: sign in again.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token: revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


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


async def require_verified_owner(
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """Owner, and the address on the account has been confirmed (teardown X2).

    Guards the two routes that link a WhatsApp number. Everything else about
    the trial stays open to an unconfirmed account -- they can explore, add
    knowledge, invite nobody and spend nothing -- because the point is to make
    a pre-registered account inert rather than to hold the product hostage
    until somebody checks their mail. What an unconfirmed account must not do
    is start answering real customers from a number, because that is the step
    that turns a squatted address into a live business identity.

    Read from the database rather than from a claim in the token. Putting it in
    the JWT would save a query and cache an authorization decision for the
    token's whole lifetime, so confirming on a laptop would leave the phone
    refusing for an hour. It is the same reason a revocation list is needed at
    all: state that can change does not belong baked into a bearer token.
    """
    tenant_id = require_owner(claims)
    # Imported here rather than at module scope: app.models imports pull in the
    # whole metadata, and deps is imported by every router.
    from app.models.tenant import User

    verified = (
        await db.execute(select(User.email_verified).where(User.email == claims.subject))
    ).scalar_one_or_none()
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "email_unverified",
                "message": (
                    "Confirm your email address before connecting a WhatsApp number. "
                    "Check your inbox for the link we sent when you signed up."
                ),
            },
        )
    return tenant_id


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
