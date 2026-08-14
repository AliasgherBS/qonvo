"""Login + current-user profile (DESIGN.md §8).

Both routes are cross-tenant lookups (email -> user -> membership), so they run
against the ``qonvo_system`` BYPASSRLS session via ``get_system_db`` rather than
a tenant-scoped one — there is no tenant to scope by until the token/credentials
resolve one.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_system_db
from app.core.security import TokenClaims, hash_password
from app.models.enums import UserRole
from app.models.tenant import Tenant, TenantConfig, TenantUser, User
from app.services.auth import authenticate, create_access_token

router = APIRouter(prefix="/api", tags=["auth"])

# Self-serve signups get a free trial; after it ends the tenant is gated until
# it's on a paid plan (§9 billing).
TRIAL_DAYS = 14


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "biz"
    # random suffix keeps the globally-unique slug constraint collision-free.
    return f"{base}-{secrets.token_hex(3)}"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str | None
    tenant_id: str | None
    name: str | None


class MeResponse(BaseModel):
    email: str
    name: str | None
    role: str | None
    tenant_id: str | None
    tenant_name: str | None


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_system_db)) -> LoginResponse:
    result = await authenticate(db, body.email, body.password)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )

    token = create_access_token(
        subject=result.user.email,
        tenant_id=result.tenant_id,
        role=result.role,
        is_qonvo_admin=result.is_qonvo_admin,
    )
    # A cross-tenant superadmin has no tenant membership role, so surface the
    # admin flag *as* the role — the dashboard gates admin nav/routes on
    # role === "qonvo_admin" (an admin otherwise arrives with role null and is
    # bounced off every /admin page onto a tenant-less, broken /inbox).
    effective_role = "qonvo_admin" if result.is_qonvo_admin else result.role
    return LoginResponse(
        access_token=token,
        role=effective_role,
        tenant_id=str(result.tenant_id) if result.tenant_id else None,
        name=result.user.full_name,
    )


class SignupRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    owner_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_system_db)) -> LoginResponse:
    """Public self-serve registration: provisions a tenant + owner on a free
    trial and returns a token (auto-login). Admins can still create tenants via
    /admin/tenants. Cross-tenant (no tenant context yet) so it runs on the
    system session, like login."""
    email = body.email.lower().strip()
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists",
        )

    tenant = Tenant(
        name=body.business_name.strip(),
        slug=_slugify(body.business_name),
        status="active",
        plan="trial",
        trial_ends_at=datetime.now(UTC) + timedelta(days=TRIAL_DAYS),
    )
    db.add(tenant)
    await db.flush()
    db.add(TenantConfig(tenant_id=tenant.id, business_name=body.business_name.strip()))
    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.owner_name.strip(),
    )
    db.add(user)
    await db.flush()
    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role=UserRole.owner))
    await db.flush()

    token = create_access_token(
        subject=user.email,
        tenant_id=tenant.id,
        role=UserRole.owner.value,
        is_qonvo_admin=False,
    )
    return LoginResponse(
        access_token=token,
        role=UserRole.owner.value,
        tenant_id=str(tenant.id),
        name=user.full_name,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> MeResponse:
    user = (await db.execute(select(User).where(User.email == claims.subject))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    tenant_name = None
    if claims.tenant_id is not None:
        tenant_name = (
            await db.execute(select(Tenant.name).where(Tenant.id == claims.tenant_id))
        ).scalar_one_or_none()

    return MeResponse(
        email=user.email,
        name=user.full_name,
        role="qonvo_admin" if claims.is_qonvo_admin else claims.role,
        tenant_id=str(claims.tenant_id) if claims.tenant_id else None,
        tenant_name=tenant_name,
    )


__all__ = ["router"]
