"""Billing provider webhook ingress (billing design §3.4, §3.5).

Deliberately knows nothing about any provider. The adapter verifies the
signature and normalises the payload; this route only decides what an
unauthentic, unknown-tenant or already-seen event means.

Uses ``system_session`` for the same reason the WAHA webhook does: the caller is
an unauthenticated machine and the tenant has to be resolved *across* tenants,
from the provider's subscription/customer id, before any tenant scope exists.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.billing.providers.base import BillingEvent, InvalidWebhookSignature
from app.billing.providers.registry import (
    UnknownBillingProvider,
    resolve_billing_provider,
)
from app.billing.service import record_event, set_subscription, subscription_fields_from_event
from app.core.logging import logger
from app.core.tenancy import system_session
from app.models.billing import Subscription
from app.models.tenant import Tenant

router = APIRouter(tags=["billing"])


async def _resolve_tenant(event: BillingEvent) -> uuid.UUID | None:
    """Find the tenant this event belongs to.

    Metadata first, then the provider's own ids.

    The order matters, and getting it wrong is silent. Matching on
    ``provider_subscription_id`` only works once a ``subscriptions`` row exists,
    and the event that creates that row is the very first one: a customer's
    first payment arrives with nothing to match against, resolves to no tenant,
    and answers 200. They would keep their old plan having paid for a new one,
    and neither they nor we would be told.

    So the adapter echoes our own tenant id back through checkout metadata, and
    this reads it. Trusting it is fine: the value originated from our own
    checkout call and the delivery carrying it has already been signature
    verified as coming from the provider.
    """
    if event.tenant_id:
        try:
            claimed = uuid.UUID(event.tenant_id)
        except (ValueError, AttributeError, TypeError):
            logger.warning(f"billing event carried an unusable tenant id: {event.tenant_id!r}")
        else:
            # Confirmed against the table rather than taken on faith. A tenant
            # deleted between checkout and payment would otherwise write
            # subscription rows nothing owns.
            async with system_session() as db:
                exists = (
                    await db.execute(select(Tenant.id).where(Tenant.id == claimed))
                ).scalar_one_or_none()
            if exists is not None:
                return claimed
            logger.warning(f"billing event named an unknown tenant: {claimed}")

    async with system_session() as db:
        for column, value in (
            (Subscription.provider_subscription_id, event.subscription_id),
            (Subscription.provider_customer_id, event.customer_id),
        ):
            if not value:
                continue
            row = (
                await db.execute(select(Subscription.tenant_id).where(column == value))
            ).scalar_one_or_none()
            if row is not None:
                return row
    return None


@router.post("/webhooks/billing/{provider}")
async def billing_webhook(provider: str, request: Request, response: Response) -> dict:
    raw = await request.body()

    try:
        adapter = resolve_billing_provider(provider)
    except UnknownBillingProvider:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"status": "unknown_provider"}

    try:
        event = adapter.parse_event(dict(request.headers), raw)
    except InvalidWebhookSignature:
        # Loud on purpose. A wrong signing secret answering 200 would look like
        # a working integration in the provider's delivery log, and nobody would
        # find out until a customer paid and got nothing.
        logger.bind(provider=provider).warning("billing webhook failed verification")
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"status": "unauthorized"}

    if event is None:
        # Authentic, just not something we act on. Providers send far more event
        # types than any integration uses, and answering an error to those gets
        # the endpoint disabled: same reasoning as the unknown-subscription case
        # below, which this used to contradict.
        logger.bind(provider=provider).info("billing webhook not actionable")
        return {"status": "ignored", "reason": "not_actionable"}

    bound = logger.bind(provider=provider, event_id=event.event_id, type=event.type)

    tenant_id = await _resolve_tenant(event)
    if tenant_id is None:
        # Answer 200: retrying will not make an unknown subscription known, and
        # a provider that keeps retrying eventually disables the endpoint.
        bound.warning("billing webhook for an unrecognised subscription")
        return {"status": "ignored", "reason": "unknown_subscription"}

    payload: dict[str, Any] = {}
    try:
        parsed = json.loads(raw)
        payload = parsed if isinstance(parsed, dict) else {"body": parsed}
    except json.JSONDecodeError:
        payload = {}

    async with system_session() as db:
        if not await record_event(db, tenant_id, event, payload):
            return {"status": "ignored", "reason": "duplicate"}
        await set_subscription(db, tenant_id, subscription_fields_from_event(event))
        await db.commit()

    bound.info("billing event applied")
    return {"status": "ok"}


__all__ = ["router"]
