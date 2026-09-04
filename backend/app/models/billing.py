"""Subscriptions and the provider event ledger (billing design §3.2).

Qonvo sells through a merchant of record, so these tables are a *reconciliation*
of what the provider says, never a source of truth about money. No amounts, no
cards, no invoices live here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin
from app.db.types import JSONBType


class Subscription(Base, TenantScopedMixin):
    """A tenant's current plan, as last reported by the billing provider."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_subscription_tenant"),
    )

    plan_key: Mapped[str] = mapped_column(String(32), nullable=False)
    # active | trialing | past_due | canceled — the provider's vocabulary,
    # normalised by the adapter. app.billing.state decides what each one means.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # When the paid-for period ends. Drives both the past_due grace window and
    # "cancelled but paid through the month" (§3.3).
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BillingEvent(Base, TenantScopedMixin):
    """Every provider event we have acted on — the idempotency ledger.

    Merchants of record retry webhooks, and retries arrive out of order. A
    replayed ``subscription.canceled`` must not cancel a tenant who has since
    resubscribed, so ``provider_event_id`` is unique and a second delivery is a
    no-op rather than a state change.
    """

    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_provider_id"),
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["BillingEvent", "Subscription"]
