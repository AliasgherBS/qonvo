"""The billing provider seam (billing design §3.4).

Everything downstream — the webhook route, the reconciler, the dashboard — speaks
only ``BillingEvent`` and ``Checkout``. Adapters translate; nothing else learns a
provider's vocabulary, which is what lets a merchant of record drop in beside the
manual adapter without touching the domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Checkout:
    """Where to send an owner who wants to upgrade.

    Exactly one of the two is set: a hosted checkout URL, or instructions for
    when there is no gateway to send them to.
    """

    url: str | None = None
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class BillingEvent:
    """A provider event, normalised.

    ``plan_key``, ``status`` and ``current_period_end`` are each optional because
    real events are partial: a payment-failure says nothing about which plan the
    tenant is on, and blanking the plan out on such an event would be a bug.
    """

    provider: str
    event_id: str
    type: str
    status: str | None = None
    plan_key: str | None = None
    subscription_id: str | None = None
    customer_id: str | None = None
    current_period_end: datetime | None = None


@runtime_checkable
class BillingProvider(Protocol):
    key: str

    def checkout(self, *, tenant_id: str, plan_key: str) -> Checkout:
        """Where to send an owner upgrading to ``plan_key``."""
        ...

    def parse_event(self, headers: dict[str, str], raw: bytes) -> BillingEvent | None:
        """Verify and normalise a webhook, or None if it is not authentic.

        Returning None rather than raising keeps signature schemes out of the
        route: it answers 401 without knowing how anything is signed.
        """
        ...


__all__ = ["BillingEvent", "BillingProvider", "Checkout"]
