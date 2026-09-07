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


class InvalidWebhookSignature(Exception):
    """This delivery could not be authenticated.

    Distinct from ``parse_event`` returning None, and the distinction is
    operational rather than cosmetic. A provider sends more event types than we
    act on, so "authentic but not interesting" is the common case and must
    answer 200: a provider that keeps getting errors eventually disables the
    endpoint, and then billing stops silently.

    A bad signature has to stay loud, though. Answering 200 to it would make a
    wrong signing secret look like a working integration in the provider's
    delivery log, and nobody would find out until a customer paid and got
    nothing.
    """


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
    #: Which tenant this is about, when the provider echoes back the metadata we
    #: sent at checkout. Load-bearing for the *first* event of a subscription:
    #: before it there is no ``subscriptions`` row, so the provider's own ids
    #: match nothing and the tenant is unresolvable without this.
    tenant_id: str | None = None
    #: What the customer was actually charged, in minor units, as reported by
    #: the provider. Not a price: prices live with the merchant of record and
    #: never in this repo. This is a fact about a payment that already happened,
    #: which is a different thing, and it is what lets a confirmation email say
    #: something true without the provider's number being duplicated anywhere.
    amount_cents: int | None = None
    currency: str | None = None
    #: The provider's own invoice reference. Quoted so a customer can match our
    #: email to the receipt the provider issued, never so we can issue one: the
    #: merchant of record is the seller and the invoice is theirs.
    invoice_number: str | None = None
    #: Why this payment happened. ``subscription_create`` is a new plan;
    #: a cycle is a renewal, and telling someone monthly that their card worked
    #: is noise the provider's own receipt already covers.
    billing_reason: str | None = None
    current_period_end: datetime | None = None


@runtime_checkable
class BillingProvider(Protocol):
    key: str

    def checkout(self, *, tenant_id: str, plan_key: str) -> Checkout:
        """Where to send an owner upgrading to ``plan_key``."""
        ...

    def parse_event(self, headers: dict[str, str], raw: bytes) -> BillingEvent | None:
        """Verify and normalise a webhook.

        Returns None for an authentic delivery this adapter does not act on, and
        raises ``InvalidWebhookSignature`` when it cannot be authenticated. The
        route needs those to mean different things and still knows nothing about
        how anything is signed.
        """
        ...


__all__ = ["BillingEvent", "BillingProvider", "Checkout", "InvalidWebhookSignature"]
