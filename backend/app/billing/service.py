"""Applying plans and reconciling provider events (billing design §3).

This module is the only place that writes billing state. Two things it is
careful about:

* **Entitlements are derived, never hand-written.** ``apply_plan`` rewrites
  ``tenant_config.entitlements`` from the catalogue, so a plan change cannot
  leave a stale quota behind.
* **Events are idempotent.** Merchants of record retry webhooks and deliver them
  out of order; ``record_event`` is the guard, and a second delivery of the same
  event id changes nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.plans import get_plan
from app.billing.providers.base import BillingEvent
from app.core.logging import logger
from app.models.billing import BillingEvent as BillingEventRow
from app.models.billing import Subscription
from app.models.tenant import Tenant, TenantConfig


def subscription_fields_from_event(event: BillingEvent) -> dict[str, Any]:
    """The subscription columns an event actually asserts.

    Absent fields are omitted rather than set to None: a payment-failed event
    says nothing about which plan the tenant is on, and writing None would erase
    it.
    """
    fields: dict[str, Any] = {
        "provider": event.provider,
        "status": event.status or "active",
    }
    if event.plan_key:
        fields["plan_key"] = event.plan_key
    if event.subscription_id:
        fields["provider_subscription_id"] = event.subscription_id
    if event.customer_id:
        fields["provider_customer_id"] = event.customer_id
    if event.current_period_end:
        fields["current_period_end"] = event.current_period_end
    return fields


async def apply_plan(db: AsyncSession, tenant_id: uuid.UUID, plan_key: str) -> None:
    """Point a tenant at a plan and rewrite its entitlements from the catalogue."""
    plan = get_plan(plan_key)

    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if config is not None:
        # JSONBType has no MutableDict, so in-place mutation is never flushed.
        config.entitlements = {**plan.entitlements}

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is not None:
        # tenants.plan stays the coarse legacy flag the admin console shows.
        tenant.plan = "trial" if plan.key == "trial" else "paid"

    logger.bind(tenant_id=str(tenant_id), plan=plan.key).info("plan applied")


async def get_subscription(db: AsyncSession, tenant_id: uuid.UUID) -> Subscription | None:
    return (
        await db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def set_subscription(
    db: AsyncSession, tenant_id: uuid.UUID, fields: dict[str, Any]
) -> Subscription:
    """Upsert the tenant's subscription and sync entitlements to its plan."""
    sub = await get_subscription(db, tenant_id)
    if sub is None:
        sub = Subscription(
            tenant_id=tenant_id,
            plan_key=fields.get("plan_key", "trial"),
        )
        db.add(sub)

    for key, value in fields.items():
        setattr(sub, key, value)

    await apply_plan(db, tenant_id, sub.plan_key)
    await db.flush()
    return sub


async def record_event(
    db: AsyncSession, tenant_id: uuid.UUID, event: BillingEvent, payload: dict[str, Any]
) -> bool:
    """Write the event to the ledger. False means we have already handled it."""
    row = BillingEventRow(
        tenant_id=tenant_id,
        provider=event.provider,
        provider_event_id=event.event_id,
        event_type=event.type,
        payload=payload,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        logger.bind(provider=event.provider, event_id=event.event_id).info(
            "billing event already processed — ignoring replay"
        )
        return False
    return True


__all__ = [
    "apply_plan",
    "get_subscription",
    "record_event",
    "set_subscription",
    "subscription_fields_from_event",
]
