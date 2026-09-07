"""First-run onboarding checklist (owner-facing, spec §8.1).

Read-only, and derived entirely from data that already exists: a linked
WhatsApp session, ingested knowledge, a configured persona, a reply the rep has
actually sent, and the activation flag. No new tables, and nothing to keep in
sync, because a checklist with its own stored "done" state drifts from reality
the first time someone deletes a knowledge source.

The last step is **activation**, which is §3's switch. That is deliberate:
onboarding and going live are one journey, and two competing surfaces both
claiming to be the last step is how an owner ends up finishing the checklist
and still having a silent rep.

Every step carries an ``href``, because a checklist that tells you what is
missing without taking you there is a list of chores.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.conversation import Message
from app.models.enums import MessageAuthor, MessageDirection, SessionStatus
from app.models.knowledge import KnowledgeSource
from app.models.skill import Integration
from app.models.tenant import Tenant, TenantConfig
from app.models.whatsapp import WhatsAppSession

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


class OnboardingStep(BaseModel):
    key: str
    label: str
    description: str
    done: bool
    required: bool  # optional steps don't block "complete"
    href: str  # where to go to satisfy it


class OnboardingStatus(BaseModel):
    steps: list[OnboardingStep]
    complete: bool  # all required steps done → tenant is live-ready
    done_count: int
    total_count: int


@router.get("", response_model=OnboardingStatus)
async def onboarding_status(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatus:
    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()

    # Persona or explicit instructions both count. A tenant can legitimately
    # run on rules alone, which the live grounding test proved.
    has_voice_and_tone = bool(
        config and (config.persona or config.tone or (config.custom_instructions or "").strip())
    )

    has_session = (
        await db.execute(
            select(WhatsAppSession.id)
            .where(
                WhatsAppSession.tenant_id == tenant_id,
                WhatsAppSession.status == SessionStatus.working,
            )
            .limit(1)
        )
    ).first() is not None

    has_knowledge = (
        await db.execute(
            select(KnowledgeSource.id)
            .where(KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.status == "ready")
            .limit(1)
        )
    ).first() is not None

    # "Tested once" means the rep has actually answered something. Checking for
    # a bot-authored outbound is the only honest version of that: an inbound
    # message alone proves the webhook works, not that the rep replied.
    has_replied = (
        await db.execute(
            select(Message.id)
            .where(
                Message.tenant_id == tenant_id,
                Message.direction == MessageDirection.outbound,
                Message.author == MessageAuthor.bot,
            )
            .limit(1)
        )
    ).first() is not None

    rep_active = bool(
        (
            await db.execute(select(Tenant.rep_active).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
    )

    has_integration = (
        await db.execute(
            select(Integration.id)
            .where(Integration.tenant_id == tenant_id, Integration.enabled.is_(True))
            .limit(1)
        )
    ).first() is not None

    steps = [
        OnboardingStep(
            key="whatsapp",
            label="Connect your WhatsApp number",
            description="Scan a QR code to link the number your customers already message.",
            done=has_session,
            required=True,
            href="/onboarding/connect",
        ),
        OnboardingStep(
            key="knowledge",
            label="Add what your rep should know",
            description="A price list, an FAQ, your policies. This is what makes it useful.",
            done=has_knowledge,
            required=True,
            href="/knowledge",
        ),
        OnboardingStep(
            key="behavior",
            label="Set how it should sound",
            description="Pick a persona and the language it replies in.",
            done=has_voice_and_tone,
            required=True,
            href="/behavior",
        ),
        OnboardingStep(
            key="tested",
            label="Send it a test message",
            description="Message your own number and read the reply before customers do.",
            done=has_replied,
            required=True,
            href="/inbox",
        ),
        OnboardingStep(
            key="activate",
            label="Turn your rep on",
            description="Until you do, messages arrive in your inbox and you answer them.",
            done=rep_active,
            required=True,
            href="/inbox",
        ),
        OnboardingStep(
            key="integrations",
            label="Connect Google",
            description="Calendar or Sheets, so it can take bookings and capture orders.",
            done=has_integration,
            required=False,
            href="/integrations",
        ),
    ]
    required = [s for s in steps if s.required]
    return OnboardingStatus(
        steps=steps,
        complete=all(s.done for s in required),
        done_count=sum(1 for s in required if s.done),
        total_count=len(required),
    )


__all__ = ["router"]
