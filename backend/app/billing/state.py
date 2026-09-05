"""May this tenant's bot reply right now? (billing design §3.3)

A pure function over the tenant's lifecycle fields, so the policy can be tested
without a database or a clock — the same split app/waha/session_recovery.py uses
for recovery decisions.

Two rules here exist because of how the money actually behaves rather than how
the states are named:

* **past_due keeps answering for a grace window.** A card failing on Tuesday must
  not silence a business on Tuesday; the merchant of record will retry it.
* **canceled keeps answering until the period ends.** They paid for the month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

#: Statuses that entitle a tenant to service outright.
_LIVE_STATUSES = frozenset({"active", "trialing"})


class BlockedReason(StrEnum):
    suspended = "suspended"
    trial_expired = "trial_expired"
    past_due = "past_due"
    canceled = "canceled"


class SubscriptionLike(Protocol):
    status: Any
    current_period_end: datetime | None


@dataclass(frozen=True, slots=True)
class ServiceState:
    allowed: bool
    blocked_reason: BlockedReason | None = None

    @property
    def gate(self) -> str:
        """Label for the pipeline's gate metric / log line."""
        return str(self.blocked_reason) if self.blocked_reason else "active"


_ALLOWED = ServiceState(allowed=True)


def service_state(
    *,
    tenant_status: str | None,
    plan: str | None,
    trial_ends_at: datetime | None,
    subscription: SubscriptionLike | None,
    now: datetime,
    grace_days: int | None = None,
) -> ServiceState:
    """Decide whether the bot may answer for this tenant."""
    if tenant_status == "suspended":
        return ServiceState(allowed=False, blocked_reason=BlockedReason.suspended)

    if subscription is not None:
        return _subscription_state(subscription, now=now, grace_days=grace_days)

    # No subscription row: every tenant predating billing. Preserve exactly the
    # behaviour they have today, so this ships without a backfill.
    if plan == "trial" and trial_ends_at is not None and trial_ends_at <= now:
        return ServiceState(allowed=False, blocked_reason=BlockedReason.trial_expired)
    return _ALLOWED


def _subscription_state(
    subscription: SubscriptionLike, *, now: datetime, grace_days: int | None
) -> ServiceState:
    status = str(subscription.status)
    period_end = subscription.current_period_end

    if status in _LIVE_STATUSES:
        return _ALLOWED

    if status == "past_due":
        if grace_days is None:
            from app.core.config import settings

            grace_days = settings.billing_grace_days
        deadline = (period_end + timedelta(days=grace_days)) if period_end else now
        if now < deadline:
            return _ALLOWED
        return ServiceState(allowed=False, blocked_reason=BlockedReason.past_due)

    if status == "canceled":
        if period_end is not None and now < period_end:
            return _ALLOWED
        return ServiceState(allowed=False, blocked_reason=BlockedReason.canceled)

    return _ALLOWED


def seats_available(
    entitlements: dict[str, Any], *, members: int, pending_invites: int
) -> int | None:
    """Seats a tenant may still fill, or ``None`` when the plan does not cap them.

    A pending invitation counts as a claimed seat: otherwise a two-seat tenant
    can send ten invitations and seat all of them. Never negative — an operator
    can move a tenant onto a smaller plan, which freezes new seats rather than
    ejecting anyone.
    """
    limit = entitlements.get("seats")
    if not limit:
        return None
    return max(0, int(limit) - members - pending_invites)


__all__ = ["BlockedReason", "ServiceState", "seats_available", "service_state"]
