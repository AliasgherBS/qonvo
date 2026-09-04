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

from app.billing.providers.base import BillingEvent
from app.billing.providers.registry import (
    UnknownBillingProvider,
    resolve_billing_provider,
)
from app.billing.service import record_event, set_subscription, subscription_fields_from_event
from app.core.logging import logger
from app.core.tenancy import system_session
from app.models.billing import Subscription

router = APIRouter(tags=["billing"])


async def _resolve_tenant(event: BillingEvent) -> uuid.UUID | None:
    """Find the tenant this event belongs to.

    Matched on the provider's own ids, since the webhook carries no Qonvo
    identity of its own. A first-ever subscription therefore needs the tenant id
    to have been passed through checkout as provider metadata, which each
    merchant-of-record adapter is responsible for supplying.
    """
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

    event = adapter.parse_event(dict(request.headers), raw)
    if event is None:
        # Covers both a bad signature and a provider that accepts no webhooks.
        logger.bind(provider=provider).warning("billing webhook rejected")
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"status": "unauthorized"}

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
