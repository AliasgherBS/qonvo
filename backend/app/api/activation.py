"""The rep's on/off switch (spec §3).

An account-level toggle, deliberately separate from the per-conversation
takeover states (``bot_active`` / ``paused_by_owner`` / ``needs_human``). That
machinery is per conversation and works; this is a different question, asked
once for the whole workspace, and overloading the two would make "paused"
ambiguous in exactly the place an owner needs it to be obvious.

The endpoint also reports what is missing, without blocking on it. An owner who
switches the rep on with an empty knowledge base gets a rep that says it does
not know the answer to most questions, which is worth warning about and is not
ours to forbid. Their number, their customers.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.knowledge import KnowledgeSource
from app.models.tenant import AuditLog, Tenant, TenantConfig
from app.models.whatsapp import WhatsAppSession

router = APIRouter(prefix="/api/activation", tags=["activation"])


class Readiness(BaseModel):
    """What is set up, so the dashboard can say what is missing.

    Advisory, not a gate. Every field is a link the UI can point at rather than
    a reason to refuse.
    """

    whatsapp_connected: bool
    has_grounding: bool
    business_name_set: bool

    @property
    def ready(self) -> bool:
        return self.whatsapp_connected and self.has_grounding and self.business_name_set


class ActivationResponse(BaseModel):
    rep_active: bool
    readiness: Readiness
    ready: bool


class ActivationRequest(BaseModel):
    rep_active: bool


async def _readiness(db: AsyncSession, tenant_id: UUID) -> Readiness:
    session_count = (
        await db.execute(
            select(func.count(WhatsAppSession.id)).where(WhatsAppSession.tenant_id == tenant_id)
        )
    ).scalar_one()

    # Either counts. A tenant can legitimately run on rules alone: the live
    # grounding test passed on custom_instructions with no documents at all.
    ready_sources = (
        await db.execute(
            select(func.count(KnowledgeSource.id)).where(
                KnowledgeSource.tenant_id == tenant_id,
                KnowledgeSource.status == "ready",
            )
        )
    ).scalar_one()
    config = (
        await db.execute(
            select(TenantConfig.custom_instructions).where(TenantConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    tenant_name = (
        await db.execute(select(Tenant.name).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()

    return Readiness(
        whatsapp_connected=bool(session_count),
        has_grounding=bool(ready_sources) or bool((config or "").strip()),
        # The seeded placeholder is not a business name. Someone who never
        # changed it has not finished setting up, whatever the column says.
        business_name_set=bool(tenant_name) and tenant_name.strip().lower() != "dev tenant",
    )


@router.get("", response_model=ActivationResponse)
async def get_activation(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ActivationResponse:
    active = (
        await db.execute(select(Tenant.rep_active).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    readiness = await _readiness(db, tenant_id)
    return ActivationResponse(
        rep_active=bool(active), readiness=readiness, ready=readiness.ready
    )


@router.put("", response_model=ActivationResponse)
async def set_activation(
    body: ActivationRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ActivationResponse:
    """Switch the rep on or off.

    No confirmation either way. Pausing has to be instant, because the reason an
    owner reaches for it is that they want the number back *now*, and a modal
    between them and that is the wrong side of the trade. Turning it on is
    equally reversible, so a warning would be theatre.

    Both transitions are audited: "the bot stopped answering" is a support
    question, and the first thing worth knowing is whether someone switched it
    off.
    """
    readiness = await _readiness(db, tenant_id)
    await db.execute(
        update(Tenant).where(Tenant.id == tenant_id).values(rep_active=body.rep_active)
    )
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=None,
            action="rep_activated" if body.rep_active else "rep_paused",
            target=str(tenant_id),
            # Recorded at the moment of the decision. Reconstructing later
            # whether the knowledge base was empty *then* is not possible.
            meta={"ready": readiness.ready, **readiness.model_dump()},
        )
    )
    await db.flush()
    return ActivationResponse(
        rep_active=body.rep_active, readiness=readiness, ready=readiness.ready
    )
