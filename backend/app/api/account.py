"""Self-serve account data export (GDPR / data portability).

Owner-facing, read-only: returns everything Qonvo holds for the tenant as one
JSON document the owner can download and keep. Tenant-scoped (RLS) — a tenant can
only ever export its own data. Deletion stays admin-mediated (``DELETE
/api/admin/tenants/{id}``) so a destructive, irreversible purge always goes
through an operator rather than a single owner click.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_owner
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


__all__ = ["router"]
