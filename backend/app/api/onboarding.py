"""First-run onboarding checklist (owner-facing).

Read-only: derives "is this tenant set up?" from data that already exists —
business info in config, a linked WhatsApp session, ingested knowledge, and any
connected integration. No new tables. The dashboard renders this as a guided
"get to live" checklist. Tenant-scoped (RLS): a tenant only ever sees itself.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.enums import SessionStatus
from app.models.knowledge import KnowledgeSource
from app.models.skill import Integration
from app.models.tenant import TenantConfig
from app.models.whatsapp import WhatsAppSession

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


class OnboardingStep(BaseModel):
    key: str
    label: str
    description: str
    done: bool
    required: bool  # optional steps don't block "complete"


class OnboardingStatus(BaseModel):
    steps: list[OnboardingStep]
    complete: bool  # all required steps done → tenant is live-ready


@router.get("", response_model=OnboardingStatus)
async def onboarding_status(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> OnboardingStatus:
    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    has_business_info = bool(config and (config.business_name or config.persona))

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

    has_integration = (
        await db.execute(
            select(Integration.id)
            .where(Integration.tenant_id == tenant_id, Integration.enabled.is_(True))
            .limit(1)
        )
    ).first() is not None

    steps = [
        OnboardingStep(
            key="business_info",
            label="Tell us about your business",
            description="Set your business name and how the assistant should sound.",
            done=has_business_info,
            required=True,
        ),
        OnboardingStep(
            key="whatsapp",
            label="Connect your WhatsApp number",
            description="Scan the QR code to link your number and go live.",
            done=has_session,
            required=True,
        ),
        OnboardingStep(
            key="knowledge",
            label="Add your knowledge",
            description="Upload docs, paste text, or add a website so the bot can answer.",
            done=has_knowledge,
            required=True,
        ),
        OnboardingStep(
            key="integrations",
            label="Connect Google (optional)",
            description="Link Calendar or Sheets to enable bookings and order capture.",
            done=has_integration,
            required=False,
        ),
    ]
    complete = all(s.done for s in steps if s.required)
    return OnboardingStatus(steps=steps, complete=complete)


__all__ = ["router"]
