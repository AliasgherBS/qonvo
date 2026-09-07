"""Owner-facing billing (§9, docs/superpowers/specs/2026-09-04-billing-design.md).

What the owner can see and do about their own plan: current status, the
catalogue, and starting an upgrade. Tenant-scoped (RLS): a tenant only ever sees
its own row.

Money is never handled here. Qonvo sells through a merchant of record, so an
upgrade hands the owner off to the configured provider — or, with the manual
adapter, tells them how to ask.
"""

from __future__ import annotations

import datetime as dt
import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.billing.plans import PLANS
from app.billing.providers.registry import resolve_billing_provider
from app.billing.service import get_subscription
from app.billing.state import service_state
from app.models.billing import Subscription
from app.models.tenant import Tenant, TenantConfig

router = APIRouter(prefix="/api/billing", tags=["billing"])


class SubscriptionInfo(BaseModel):
    plan_key: str
    status: str
    provider: str
    current_period_end: dt.datetime | None
    cancel_at_period_end: bool


class BillingStatus(BaseModel):
    plan: str
    status: str
    trial_ends_at: dt.datetime | None
    days_left: int | None  # whole days until the trial ends (0 if past); null when not on trial
    expired: bool  # service is blocked → bot is silent
    blocked_reason: str | None  # why, when expired: suspended/trial_expired/past_due/canceled
    subscription: SubscriptionInfo | None
    entitlements: dict


class PlanInfo(BaseModel):
    key: str
    name: str
    entitlements: dict


class CheckoutRequest(BaseModel):
    plan_key: str


class CheckoutResponse(BaseModel):
    url: str | None
    instructions: str | None


@router.get("/payments")
async def payment_history(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """This tenant's payments, newest first.

    Read from the provider rather than from our own ``billing_events``. Their
    ledger is the authoritative one: it knows about refunds and about anything
    charged before our webhook existed, and ours only knows what it was told.
    A history that disagrees with the customer's card statement is worse than
    no history.

    Empty rather than an error when there is nothing to read, which is the
    normal state for a tenant still on the trial.
    """
    customer_id = (
        await db.execute(
            select(Subscription.provider_customer_id).where(Subscription.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not customer_id:
        return []

    payments = resolve_billing_provider().payments(customer_id=customer_id)
    return [
        {
            "date": p.date.isoformat(),
            "amount_cents": p.amount_cents,
            "currency": p.currency,
            "status": p.status,
            "invoice_number": p.invoice_number,
            "description": p.description,
            "invoice_url": p.invoice_url,
        }
        for p in payments
    ]


@router.post("/portal")
async def billing_portal(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A link to the provider's billing portal, minted fresh.

    Cancelling, changing a card and downloading an invoice all live there. That
    is not laziness: the merchant of record owns the subscription and issues the
    tax document, so a cancel button of our own would give two systems an
    opinion about the same subscription, and ours would be the one that was
    wrong after a dunning retry.

    POST rather than GET because it creates a session, and the token expires,
    so it is minted per click rather than stored.
    """
    customer_id = (
        await db.execute(
            select(Subscription.provider_customer_id).where(Subscription.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if not customer_id:
        return {"url": None, "reason": "no_subscription"}

    url = resolve_billing_provider().portal_url(customer_id=customer_id)
    return {"url": url, "reason": None if url else "unavailable"}


@router.get("/usage")
async def billing_usage(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every meter for this tenant.

    Reads ``services.usage.tenant_usage``, which is also what the admin console
    reads. That is the point of §4.3: one computation, so an owner and an
    operator looking at the same tenant cannot be shown different numbers.
    """
    from app.services.usage import tenant_usage

    return (await tenant_usage(db, tenant_id)).as_dict()


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
            plan="trial",
            status="active",
            trial_ends_at=None,
            days_left=None,
            expired=False,
            blocked_reason=None,
            subscription=None,
            entitlements={},
        )

    now = dt.datetime.now(dt.UTC)
    subscription = await get_subscription(db, tenant_id)
    state = service_state(
        tenant_status=row.status,
        plan=row.plan,
        trial_ends_at=row.trial_ends_at,
        subscription=subscription,
        now=now,
    )

    days_left: int | None = None
    if row.plan == "trial" and row.trial_ends_at is not None:
        days_left = max(0, math.ceil((row.trial_ends_at - now).total_seconds() / 86_400))

    entitlements = (
        await db.execute(
            select(TenantConfig.entitlements).where(TenantConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    return BillingStatus(
        plan=row.plan,
        status=row.status,
        trial_ends_at=row.trial_ends_at,
        days_left=days_left,
        expired=not state.allowed,
        blocked_reason=str(state.blocked_reason) if state.blocked_reason else None,
        subscription=(
            SubscriptionInfo(
                plan_key=subscription.plan_key,
                status=subscription.status,
                provider=subscription.provider,
                current_period_end=subscription.current_period_end,
                cancel_at_period_end=subscription.cancel_at_period_end,
            )
            if subscription is not None
            else None
        ),
        entitlements=entitlements or {},
    )


@router.get("/plans", response_model=list[PlanInfo])
async def list_plans(_tenant_id: UUID = Depends(require_tenant)) -> list[PlanInfo]:
    """The catalogue, in upgrade order. Prices live with the payment provider."""
    return [
        PlanInfo(key=plan.key, name=plan.name, entitlements=plan.entitlements)
        for plan in PLANS.values()
    ]


@router.post("/checkout", response_model=CheckoutResponse)
async def start_checkout(
    body: CheckoutRequest,
    tenant_id: UUID = Depends(require_tenant),
) -> CheckoutResponse:
    if body.plan_key not in PLANS:
        raise HTTPException(status_code=400, detail="unknown plan")
    if body.plan_key == "trial":
        raise HTTPException(status_code=400, detail="cannot check out onto the trial plan")

    checkout = resolve_billing_provider().checkout(
        tenant_id=str(tenant_id), plan_key=body.plan_key
    )
    return CheckoutResponse(url=checkout.url, instructions=checkout.instructions)


__all__ = ["router"]
