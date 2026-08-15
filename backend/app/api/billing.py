"""Owner-facing billing/trial status (§9).

Read-only view of the tenant's plan + trial so the dashboard can show a
days-left indicator and an upgrade prompt. Tenant-scoped (RLS): a tenant only
ever sees its own row.
"""

from __future__ import annotations

import datetime as dt
import math
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.tenant import Tenant

router = APIRouter(prefix="/api/billing", tags=["billing"])


class BillingStatus(BaseModel):
    plan: str
    status: str
    trial_ends_at: dt.datetime | None
    days_left: int | None  # whole days until the trial ends (0 if past); null when not on trial
    expired: bool  # trial is over (or tenant suspended) → bot is silent


@router.get("", response_model=BillingStatus)
async def billing_status(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> BillingStatus:
    row = (
        await db.execute(
            select(Tenant.plan, Tenant.status, Tenant.trial_ends_at).where(Tenant.id == tenant_id)
        )
    ).one_or_none()
    if row is None:
        return BillingStatus(
            plan="trial", status="active", trial_ends_at=None, days_left=None, expired=False
        )

    days_left: int | None = None
    trial_over = False
    if row.plan == "trial" and row.trial_ends_at is not None:
        seconds = (row.trial_ends_at - dt.datetime.now(dt.UTC)).total_seconds()
        days_left = max(0, math.ceil(seconds / 86_400))
        trial_over = seconds <= 0

    return BillingStatus(
        plan=row.plan,
        status=row.status,
        trial_ends_at=row.trial_ends_at,
        days_left=days_left,
        expired=trial_over or row.status == "suspended",
    )


__all__ = ["router"]
