"""Login + current-user profile (DESIGN.md §8).

Both routes are cross-tenant lookups (email -> user -> membership), so they run
against the ``qonvo_system`` BYPASSRLS session via ``get_system_db`` rather than
a tenant-scoped one — there is no tenant to scope by until the token/credentials
resolve one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_system_db
from app.core.config import settings
from app.core.security import TokenClaims
from app.models.tenant import Tenant, User
from app.services.auth import (
    AuthResult,
    authenticate,
    change_password,
    create_access_token,
    create_password_reset_token,
    find_user,
    provision_tenant,
    reset_password,
    resolve_login,
)
from app.services.email import send_password_reset_email, send_welcome_email
from app.services.google_identity import GoogleIdentityError, verify_google_id_token

router = APIRouter(prefix="/api", tags=["auth"])


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


def _login_response(result: AuthResult) -> LoginResponse:
    """Mint the JWT and shape the response for any successful identification."""
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


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_system_db)) -> LoginResponse:
    result = await authenticate(db, body.email, body.password)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )
    return _login_response(result)


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
    if await find_user(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists",
        )

    result = await provision_tenant(
        db,
        business_name=body.business_name,
        owner_name=body.owner_name,
        email=email,
        password=body.password,
    )
    await send_welcome_email(email, body.owner_name, body.business_name)
    return _login_response(result)


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=1)
    # Only used when this Google account is new here; otherwise ignored.
    business_name: str | None = Field(default=None, max_length=255)


@router.post("/auth/google", response_model=LoginResponse)
async def google_auth(
    body: GoogleAuthRequest, db: AsyncSession = Depends(get_system_db)
) -> LoginResponse:
    """Sign in (or sign up) with Google.

    Deliberately separate from the integrations OAuth flow. Both use the same
    Google client, but this one asks only for identity — merging them would demand
    Calendar permission from every new signup before they've seen the product,
    which is the fastest way to lose them. Calendar/Sheets consent is requested
    later, from the Integrations page, when the owner actually enables that
    feature (incremental authorization).

    Cross-tenant like login/signup, so it runs on the system session.
    """
    try:
        identity = await verify_google_id_token(body.id_token)
    except GoogleIdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    user = await find_user(db, identity.email)
    if user is not None:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="this account is disabled"
            )
        # Backfill a name for accounts created before they had one.
        if not user.full_name and identity.full_name:
            user.full_name = identity.full_name
            await db.flush()
        return _login_response(await resolve_login(db, user))

    # New Google account → provision a tenant, same as self-serve signup. Fall
    # back to the display name for the business, since the owner can rename it in
    # Settings and blocking signup for a missing field would be worse.
    business_name = (
        (body.business_name or "").strip()
        or identity.full_name
        or identity.email.split("@")[0]
    )
    result = await provision_tenant(
        db,
        business_name=business_name,
        owner_name=identity.full_name,
        email=identity.email,
        password=None,
    )
    await send_welcome_email(identity.email, identity.full_name, business_name)
    return _login_response(result)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password_route(
    body: ChangePasswordRequest,
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> None:
    """Change the signed-in user's password (verifies the current one)."""
    user = await find_user(db, claims.subject)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if not await change_password(db, user, body.current_password, body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect."
        )


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password_route(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_system_db)
) -> dict:
    """Email a password-reset link. Always returns 202 — never reveals whether an
    account exists (no user enumeration)."""
    user = await find_user(db, body.email)
    if user is not None and user.is_active:
        token = create_password_reset_token(user)
        reset_url = f"{settings.dashboard_base_url}/reset-password?token={token}"
        await send_password_reset_email(user.email, user.full_name, reset_url)
    return {"status": "ok"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password_route(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_system_db)
) -> None:
    """Set a new password from a reset-link token (single-use, 30-min expiry)."""
    if not await reset_password(db, body.token, body.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired.",
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
