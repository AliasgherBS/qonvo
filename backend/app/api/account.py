"""The person's own account: their profile, and a data export (GDPR).

Two surfaces, deliberately in one module because both are about *you* rather
than about the workspace.

The export is owner-facing and read-only: everything Qonvo holds for the tenant
as one JSON document the owner can download and keep. Tenant-scoped (RLS) — a
tenant can only ever export its own data. Deletion stays admin-mediated
(``DELETE /api/admin/tenants/{id}``) so a destructive, irreversible purge always
goes through an operator rather than a single owner click.

The profile is per-person and tenant-independent, which is why it is gated on
``get_claims`` rather than on ``require_tenant`` or ``require_owner``: a display
name belongs to the human, a cross-tenant admin has no tenant at all, and a
staff seat whose name was typed wrong at signup has the same right to fix it as
an owner (teardown V5). ``PATCH /api/account/profile`` is therefore listed in
``tests/test_route_authorization.py::STAFF_ALLOWED``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_db, get_system_db, require_owner
from app.core.security import TokenClaims
from app.models.business import Booking, Lead, Order
from app.models.conversation import Conversation, Message
from app.models.knowledge import KnowledgeSource
from app.models.tenant import Tenant, TenantConfig, TenantUser, User

router = APIRouter(prefix="/api/account", tags=["account"])


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, dt.datetime) else value


def _row_to_dict(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: _iso(getattr(obj, f, None)) for f in fields}


@router.get("/export")
async def export_account(
    tenant_id: UUID = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """One JSON document with the tenant's profile, team, knowledge, conversations
    (with messages), and captured leads/orders/bookings."""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()

    members = (
        await db.execute(
            select(TenantUser.role, User.email, User.full_name)
            .join(User, User.id == TenantUser.user_id)
            .where(TenantUser.tenant_id == tenant_id)
        )
    ).all()

    conversations = (
        (
            await db.execute(
                select(Conversation)
                .where(Conversation.tenant_id == tenant_id)
                .order_by(Conversation.created_at)
            )
        )
        .scalars()
        .all()
    )
    messages = (
        (
            await db.execute(
                select(Message).where(Message.tenant_id == tenant_id).order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    msgs_by_conv: dict[str, list[dict]] = {}
    for m in messages:
        msgs_by_conv.setdefault(str(m.conversation_id), []).append(
            _row_to_dict(m, ("direction", "author", "type", "body", "transcript", "created_at"))
        )

    sources = (
        (await db.execute(select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    leads = (await db.execute(select(Lead).where(Lead.tenant_id == tenant_id))).scalars().all()
    orders = (await db.execute(select(Order).where(Order.tenant_id == tenant_id))).scalars().all()
    bookings = (
        (await db.execute(select(Booking).where(Booking.tenant_id == tenant_id))).scalars().all()
    )

    return {
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "tenant": _row_to_dict(tenant, ("id", "name", "slug", "status", "plan", "created_at"))
        if tenant
        else None,
        "config": _row_to_dict(
            config,
            (
                "business_name",
                "persona",
                "tone",
                "primary_language",
                "custom_instructions",
                "business_hours",
                "payment_details",
            ),
        )
        if config
        else None,
        "team": [
            {"email": r.email, "full_name": r.full_name, "role": str(r.role)} for r in members
        ],
        "knowledge_sources": [
            _row_to_dict(s, ("name", "type", "url", "status", "created_at")) for s in sources
        ],
        "conversations": [
            {
                **_row_to_dict(c, ("id", "chat_id", "state", "created_at")),
                "messages": msgs_by_conv.get(str(c.id), []),
            }
            for c in conversations
        ],
        "leads": [_row_to_dict(x, ("name", "phone", "notes", "created_at")) for x in leads],
        "orders": [
            _row_to_dict(x, ("customer_name", "items", "status", "created_at")) for x in orders
        ],
        "bookings": [
            _row_to_dict(x, ("customer_phone", "scheduled_at", "status", "created_at"))
            for x in bookings
        ],
    }


# --------------------------------------------------------------------------- #
# Profile (teardown V5, V6)
# --------------------------------------------------------------------------- #
#: The column is String(255); a name longer than this is a paste, not a name.
MAX_FULL_NAME = 120


class ProfileResponse(BaseModel):
    email: str
    full_name: str | None
    role: str | None
    #: So the Account page can say whether a second factor is on without
    #: needing an endpoint of its own. Never the secret, which only
    #: ``/api/auth/totp/start`` returns and only once.
    totp_enabled: bool


class ProfileUpdateRequest(BaseModel):
    full_name: str

    @field_validator("full_name")
    @classmethod
    def _clean_full_name(cls, v: str) -> str:
        # Trimmed, not rejected for whitespace: a trailing space from a paste is
        # not worth an error. Empty after trimming is refused, because a blank
        # name would leave the person as an initial-less avatar and an unnamed
        # row in the Team list.
        v = " ".join(v.split())
        if not v:
            raise ValueError("Your name cannot be empty")
        if len(v) > MAX_FULL_NAME:
            raise ValueError(f"Your name must be {MAX_FULL_NAME} characters or fewer")
        return v


async def _current_user(db: AsyncSession, claims: TokenClaims) -> User:
    user = (await db.execute(select(User).where(User.email == claims.subject))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


def _profile(user: User, claims: TokenClaims) -> ProfileResponse:
    return ProfileResponse(
        email=user.email,
        full_name=user.full_name,
        role="qonvo_admin" if claims.is_qonvo_admin else claims.role,
        totp_enabled=user.totp_enabled,
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    claims: TokenClaims = Depends(get_claims),
    # The system session, because ``users`` is not tenant-scoped and the caller
    # may have no tenant at all. Nothing cross-tenant is read: the row is looked
    # up by the subject of the caller's own token.
    db: AsyncSession = Depends(get_system_db),
) -> ProfileResponse:
    return _profile(await _current_user(db, claims), claims)


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_system_db),
) -> ProfileResponse:
    """Change your own display name.

    The name in the avatar menu, in the Team list and on every invitation you
    send was captured once at signup and could never be changed, from here or
    anywhere else: a Google signup took it from the Google profile and a typo
    was permanent (teardown V5).

    Only ever the caller's own row. There is no user id in the payload on
    purpose, so this cannot become a way to rename somebody else.
    """
    user = await _current_user(db, claims)
    user.full_name = body.full_name
    await db.flush()
    return _profile(user, claims)


__all__ = ["MAX_FULL_NAME", "ProfileUpdateRequest", "router"]
