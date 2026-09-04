"""Team seats — invite staff/co-owners to a tenant (owner-managed).

Two surfaces:
- **Owner-managed** (`get_db`, RLS): list members + invitations, invite, revoke,
  remove a member. Mutations require the ``owner`` role.
- **Public accept** (`system_session`, BYPASSRLS): the invitee isn't a member of
  the tenant yet, and the invite token must be resolved without knowing the
  tenant — a trusted cross-tenant lookup, exactly like webhook tenant resolution.
  It creates (or reuses) the ``User`` + a ``tenant_users`` membership and mints a
  login token.
"""

from __future__ import annotations

import datetime as dt
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_system_db, require_owner, require_tenant
from app.billing.state import seats_available
from app.core.config import settings
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.tenant import TeamInvitation, Tenant, TenantConfig, TenantUser, User
from app.services.auth import create_access_token
from app.services.email import send_team_invite_email

router = APIRouter(prefix="/api/team", tags=["team"])

INVITE_TTL_DAYS = 7
_ROLES = {"owner", "staff"}


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #
class MemberResponse(BaseModel):
    user_id: UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool


class InvitationResponse(BaseModel):
    id: UUID
    email: str
    role: str
    status: str
    expires_at: dt.datetime


class TeamResponse(BaseModel):
    members: list[MemberResponse]
    invitations: list[InvitationResponse]  # pending only


# --------------------------------------------------------------------------- #
# Owner-managed (RLS)
# --------------------------------------------------------------------------- #
@router.get("", response_model=TeamResponse)
async def get_team(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> TeamResponse:
    member_rows = (
        await db.execute(
            select(TenantUser.user_id, TenantUser.role, User.email, User.full_name, User.is_active)
            .join(User, User.id == TenantUser.user_id)
            .where(TenantUser.tenant_id == tenant_id)
            .order_by(TenantUser.created_at)
        )
    ).all()
    invite_rows = (
        (
            await db.execute(
                select(TeamInvitation)
                .where(TeamInvitation.tenant_id == tenant_id, TeamInvitation.status == "pending")
                .order_by(TeamInvitation.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    now = dt.datetime.now(dt.UTC)
    return TeamResponse(
        members=[
            MemberResponse(
                user_id=r.user_id,
                email=r.email,
                full_name=r.full_name,
                role=str(r.role),
                is_active=r.is_active,
            )
            for r in member_rows
        ],
        invitations=[
            InvitationResponse(
                id=i.id, email=i.email, role=i.role, status=i.status, expires_at=i.expires_at
            )
            for i in invite_rows
            if i.expires_at > now
        ],
    )


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "staff"


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    body: InviteRequest,
    tenant_id: UUID = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    if body.role not in _ROLES:
        raise HTTPException(status_code=400, detail="role must be owner or staff")
    email = body.email.lower()

    # Already a member? (cross-check via the global users table + membership.)
    existing_member = (
        await db.execute(
            select(TenantUser.user_id)
            .join(User, User.id == TenantUser.user_id)
            .where(TenantUser.tenant_id == tenant_id, User.email == email)
        )
    ).first()
    if existing_member is not None:
        raise HTTPException(status_code=409, detail="already a team member")

    # Seat entitlement (§3.1). Pending invites count as claimed seats, so a
    # tenant cannot outrun its plan by sending invitations in a batch.
    entitlements = (
        await db.execute(
            select(TenantConfig.entitlements).where(TenantConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none() or {}
    members = (
        await db.execute(
            select(func.count())
            .select_from(TenantUser)
            .where(TenantUser.tenant_id == tenant_id)
        )
    ).scalar_one()
    pending = (
        await db.execute(
            select(func.count())
            .select_from(TeamInvitation)
            .where(
                TeamInvitation.tenant_id == tenant_id,
                TeamInvitation.status == "pending",
                TeamInvitation.email != email,
            )
        )
    ).scalar_one()
    remaining = seats_available(entitlements, members=members, pending_invites=pending)
    if remaining is not None and remaining < 1:
        raise HTTPException(
            status_code=402,
            detail="No seats left on your plan. Upgrade to invite more teammates.",
        )

    # Revoke any earlier pending invite for the same email (one live invite/email).
    for prior in (
        (
            await db.execute(
                select(TeamInvitation).where(
                    TeamInvitation.tenant_id == tenant_id,
                    TeamInvitation.email == email,
                    TeamInvitation.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    ):
        prior.status = "revoked"

    token = secrets.token_urlsafe(32)
    invite = TeamInvitation(
        tenant_id=tenant_id,
        email=email,
        role=body.role,
        token=token,
        status="pending",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    await db.flush()

    business = (
        await db.execute(select(Tenant.name).where(Tenant.id == tenant_id))
    ).scalar_one_or_none() or "the team"
    accept_url = f"{settings.dashboard_base_url}/accept-invite?token={token}"
    await send_team_invite_email(email, business, body.role, accept_url)

    return InvitationResponse(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        status=invite.status,
        expires_at=invite.expires_at,
    )


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID,
    tenant_id: UUID = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    invite = (
        await db.execute(select(TeamInvitation).where(TeamInvitation.id == invitation_id))
    ).scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="invitation not found")
    invite.status = "revoked"
    await db.flush()


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: UUID,
    tenant_id: UUID = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    members = (
        (await db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    target = next((m for m in members if m.user_id == user_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="member not found")
    # Don't strand the tenant: never remove the last owner.
    if target.role == UserRole.owner:
        owner_count = sum(1 for m in members if m.role == UserRole.owner)
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="cannot remove the last owner")
    await db.delete(target)
    await db.flush()


# --------------------------------------------------------------------------- #
# Public accept (cross-tenant, token-authenticated → system_session)
# --------------------------------------------------------------------------- #
class InvitePreview(BaseModel):
    valid: bool
    email: str | None = None
    role: str | None = None
    business_name: str | None = None
    needs_password: bool = False  # true when the invitee has no account yet
    reason: str | None = None


async def _resolve_invite(db: AsyncSession, token: str) -> TeamInvitation | None:
    invite = (
        await db.execute(select(TeamInvitation).where(TeamInvitation.token == token))
    ).scalar_one_or_none()
    if invite is None or invite.status != "pending":
        return None
    if invite.expires_at <= dt.datetime.now(dt.UTC):
        return None
    return invite


@router.get("/invitations/accept/{token}", response_model=InvitePreview)
async def preview_invitation(
    token: str,
    db: AsyncSession = Depends(get_system_db),
) -> InvitePreview:
    invite = await _resolve_invite(db, token)
    if invite is None:
        return InvitePreview(valid=False, reason="This invitation is invalid, used, or expired.")
    business = (
        await db.execute(select(Tenant.name).where(Tenant.id == invite.tenant_id))
    ).scalar_one_or_none()
    user = (
        await db.execute(select(User).where(User.email == invite.email))
    ).scalar_one_or_none()
    return InvitePreview(
        valid=True,
        email=invite.email,
        role=invite.role,
        business_name=business,
        needs_password=user is None or user.hashed_password is None,
    )


class AcceptRequest(BaseModel):
    token: str
    password: str | None = None
    full_name: str | None = None


class AcceptResponse(BaseModel):
    access_token: str
    tenant_id: UUID
    email: str
    role: str


@router.post("/invitations/accept", response_model=AcceptResponse)
async def accept_invitation(
    body: AcceptRequest,
    db: AsyncSession = Depends(get_system_db),
) -> AcceptResponse:
    invite = await _resolve_invite(db, body.token)
    if invite is None:
        raise HTTPException(status_code=400, detail="invitation is invalid, used, or expired")

    role = UserRole.owner if invite.role == "owner" else UserRole.staff
    user = (
        await db.execute(select(User).where(User.email == invite.email))
    ).scalar_one_or_none()
    if user is None:
        if not body.password:
            raise HTTPException(status_code=400, detail="password required for a new account")
        user = User(
            email=invite.email,
            hashed_password=hash_password(body.password),
            full_name=(body.full_name or "").strip() or None,
        )
        db.add(user)
        await db.flush()
    elif user.hashed_password is None and body.password:
        user.hashed_password = hash_password(body.password)

    # Add membership if not already present (idempotent accept).
    membership = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == invite.tenant_id, TenantUser.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(TenantUser(tenant_id=invite.tenant_id, user_id=user.id, role=role))

    invite.status = "accepted"
    invite.accepted_at = dt.datetime.now(dt.UTC)
    await db.flush()

    token = create_access_token(
        subject=user.email,
        tenant_id=invite.tenant_id,
        role=role.value,
        is_qonvo_admin=False,
    )
    return AcceptResponse(
        access_token=token, tenant_id=invite.tenant_id, email=user.email, role=role.value
    )


__all__ = ["router"]
