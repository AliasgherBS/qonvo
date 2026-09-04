"""Authentication service: password login + JWT minting (DESIGN.md §8).

Login runs against the global ``users`` table (not tenant-scoped) plus the user's
``tenant_users`` membership, so it must use a session that can see across tenants
(the caller passes the system session). The minted JWT carries ``sub`` (email),
``tenant_id``, ``role``, and the cross-tenant ``qonvo_admin`` flag, consumed by
``app.core.security.decode_jwt`` on every subsequent request.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
from dataclasses import dataclass
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.plans import TRIAL_PLAN, get_plan
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.enums import UserRole
from app.models.tenant import Tenant, TenantConfig, TenantUser, User

# Self-serve signups get a free trial; after it ends the tenant is gated until
# it's on a paid plan (§9 billing).
TRIAL_DAYS = 14
# Hard message cap for a trial tenant — bounds LLM/voice spend for a free signup
# (the date check alone left trials able to burn unlimited credits for 14 days).
TRIAL_MESSAGE_QUOTA = get_plan(TRIAL_PLAN).entitlements["monthly_message_quota"]

# Password-reset links expire after this long.
PASSWORD_RESET_TTL_MINUTES = 30


def _password_fingerprint(user: User) -> str:
    """A short token that changes whenever the user's password changes.

    Embedding it in a reset link makes the link single-use and self-invalidating:
    once the password is set (by this reset or any change), outstanding links no
    longer match. Stateless — no reset-token table needed.
    """
    base = f"{user.id}:{user.hashed_password or 'none'}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def create_password_reset_token(user: User) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": user.email,
        "typ": "pwreset",
        "pwf": _password_fingerprint(user),
        "iat": now,
        "exp": now + dt.timedelta(minutes=PASSWORD_RESET_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_password_reset_token(token: str) -> tuple[str, str] | None:
    """Return ``(email, password_fingerprint)`` if the token is a valid, unexpired
    reset token, else ``None``. The caller re-checks the fingerprint against the
    live user to enforce single-use."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "pwreset":
        return None
    email, pwf = payload.get("sub"), payload.get("pwf")
    if not isinstance(email, str) or not isinstance(pwf, str):
        return None
    return email, pwf


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> bool:
    """Set a new password after verifying the current one. False if it's wrong."""
    if not verify_password(current, user.hashed_password):
        return False
    user.hashed_password = hash_password(new)
    await db.flush()
    return True


async def reset_password(db: AsyncSession, token: str, new: str) -> bool:
    """Consume a reset token and set the new password. False if invalid/used."""
    parsed = read_password_reset_token(token)
    if parsed is None:
        return False
    email, pwf = parsed
    user = await find_user(db, email)
    # Fingerprint mismatch = the password already changed since the link was
    # issued (link reused or superseded) → reject.
    if user is None or not user.is_active or _password_fingerprint(user) != pwf:
        return False
    user.hashed_password = hash_password(new)
    await db.flush()
    return True


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


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "biz"
    # random suffix keeps the globally-unique slug constraint collision-free.
    return f"{base}-{secrets.token_hex(3)}"


async def find_user(db: AsyncSession, email: str) -> User | None:
    return (
        await db.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()


async def resolve_login(db: AsyncSession, user: User) -> AuthResult:
    """Wrap an already-identified user as an :class:`AuthResult`.

    Shared by password login and Google SSO so both resolve the acting tenant the
    same way — including the qonvo_admin case, which legitimately has no
    membership.
    """
    membership = await _resolve_membership(db, user.id)
    if membership is None:
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


async def provision_tenant(
    db: AsyncSession,
    *,
    business_name: str,
    owner_name: str | None,
    email: str,
    password: str | None = None,
) -> AuthResult:
    """Create a tenant + config + owner user + membership on a free trial.

    ``password=None`` is the Google-SSO case. ``users.hashed_password`` is nullable
    and ``verify_password`` returns False for a null hash, so such an account
    simply can't be signed into with a password — no placeholder hash needed.

    Cross-tenant by nature (there is no tenant yet), so callers pass the system
    session.
    """
    business_name = business_name.strip()
    tenant = Tenant(
        name=business_name,
        slug=slugify(business_name),
        status="active",
        plan="trial",
        trial_ends_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=TRIAL_DAYS),
    )
    db.add(tenant)
    await db.flush()
    db.add(
        TenantConfig(
            tenant_id=tenant.id,
            business_name=business_name,
            # Trial tenants get a hard message cap so a free signup can't burn
            # unlimited LLM/voice credits (enforced by the pipeline's quota gate).
            # Derived from the plan catalogue so the trial's entitlements can
            # never drift from what /api/billing/plans advertises.
            entitlements={**get_plan(TRIAL_PLAN).entitlements},
        )
    )

    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password) if password else None,
        full_name=(owner_name or "").strip() or None,
    )
    db.add(user)
    await db.flush()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role=UserRole.owner))
    await db.flush()

    return AuthResult(
        user=user,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=UserRole.owner.value,
        is_qonvo_admin=False,
    )


__all__ = [
    "TRIAL_DAYS",
    "AuthResult",
    "authenticate",
    "change_password",
    "create_access_token",
    "create_password_reset_token",
    "find_user",
    "provision_tenant",
    "read_password_reset_token",
    "reset_password",
    "resolve_login",
    "slugify",
]
