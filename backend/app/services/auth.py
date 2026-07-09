"""Authentication service: password login + JWT minting (DESIGN.md §8).

Login runs against the global ``users`` table (not tenant-scoped) plus the user's
``tenant_users`` membership, so it must use a session that can see across tenants
(the caller passes the system session). The minted JWT carries ``sub`` (email),
``tenant_id``, ``role``, and the cross-tenant ``qonvo_admin`` flag, consumed by
``app.core.security.decode_jwt`` on every subsequent request.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_password
from app.models.tenant import Tenant, TenantUser, User


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Resolved identity for a successful login."""

    user: User
    tenant_id: UUID | None
    tenant_name: str | None
    role: str | None
    is_qonvo_admin: bool


def create_access_token(
    *,
    subject: str,
    tenant_id: UUID | None,
    role: str | None,
    is_qonvo_admin: bool,
) -> str:
    """Mint a signed JWT with tenant/role claims and a ``jwt_expiry_hours`` TTL."""
    now = dt.datetime.now(dt.UTC)
    payload: dict = {
        "sub": subject,
        "role": role,
        "qonvo_admin": is_qonvo_admin,
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.jwt_expiry_hours),
    }
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _resolve_membership(
    db: AsyncSession, user_id: UUID
) -> tuple[UUID, str, str | None] | None:
    """Return ``(tenant_id, role, tenant_name)`` for the user's first membership."""
    row = (
        await db.execute(
            select(TenantUser.tenant_id, TenantUser.role, Tenant.name)
            .join(Tenant, Tenant.id == TenantUser.tenant_id)
            .where(TenantUser.user_id == user_id)
            .order_by(TenantUser.created_at)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    tenant_id, role, tenant_name = row
    return tenant_id, str(role), tenant_name


async def authenticate(db: AsyncSession, email: str, password: str) -> AuthResult | None:
    """Verify credentials and resolve the acting tenant.

    Returns ``None`` for an unknown email, a bad password, or an inactive user —
    the route maps every ``None`` to a single 401 so the response does not reveal
    which check failed.
    """
    user = (
        await db.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None

    membership = await _resolve_membership(db, user.id)
    if membership is None:
        # A qonvo_admin may legitimately have no tenant membership.
        return AuthResult(
            user=user,
            tenant_id=None,
            tenant_name=None,
            role=None,
            is_qonvo_admin=user.is_qonvo_admin,
        )
    tenant_id, role, tenant_name = membership
    return AuthResult(
        user=user,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        role=role,
        is_qonvo_admin=user.is_qonvo_admin,
    )


__all__ = ["AuthResult", "authenticate", "create_access_token"]
