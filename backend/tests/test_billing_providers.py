"""Billing provider adapters and event normalisation (billing design §3.4).

The point of these tests is that the route and the reconciler never learn any
provider's vocabulary: adapters translate into ``BillingEvent``, and everything
downstream sees only that.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.billing.providers.base import BillingEvent, Checkout
from app.billing.providers.manual import ManualProvider
from app.billing.providers.registry import UnknownBillingProvider, resolve_billing_provider
from app.billing.service import subscription_fields_from_event

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _event(**overrides) -> BillingEvent:
    base = {
        "provider": "fake",
        "event_id": "evt_1",
        "type": "subscription.updated",
        "plan_key": "growth",
        "status": "active",
        "subscription_id": "sub_1",
        "customer_id": "cus_1",
        "current_period_end": NOW,
    }
    base.update(overrides)
    return BillingEvent(**base)


# --- the manual adapter ------------------------------------------------------ #
def test_manual_checkout_tells_the_owner_what_to_do_instead_of_redirecting():
    """With no gateway connected, an upgrade is a conversation, not a 500."""
    checkout = ManualProvider().checkout(tenant_id="t1", plan_key="growth")

    assert isinstance(checkout, Checkout)
    assert checkout.url is None
    assert checkout.instructions


def test_manual_provider_accepts_no_webhooks():
    """Nothing signs manual events, so the webhook route must reject them."""
    assert ManualProvider().parse_event({}, b"{}") is None


# --- the registry ------------------------------------------------------------ #
def test_registry_defaults_to_manual():
    assert resolve_billing_provider().key == "manual"


def test_registry_rejects_an_unconfigured_provider(monkeypatch):
    """A typo in QONVO_BILLING_PROVIDER must fail loudly at resolve time, not
    silently fall back to manual and quietly stop taking money."""
    from app.billing.providers import registry

    monkeypatch.setattr(registry.settings, "billing_provider", "stripe")
    with pytest.raises(UnknownBillingProvider):
        resolve_billing_provider()


# --- event → subscription fields --------------------------------------------- #
def test_event_maps_onto_subscription_fields():
    fields = subscription_fields_from_event(_event())

    assert fields == {
        "plan_key": "growth",
        "status": "active",
        "provider": "fake",
        "provider_subscription_id": "sub_1",
        "provider_customer_id": "cus_1",
        "current_period_end": NOW,
    }


def test_an_event_without_a_plan_leaves_the_plan_alone():
    """A payment-failed event says nothing about which plan they are on; it must
    not blank the plan out."""
    fields = subscription_fields_from_event(_event(plan_key=None, status="past_due"))

    assert "plan_key" not in fields
    assert fields["status"] == "past_due"


def test_an_event_without_a_period_end_leaves_the_period_alone():
    fields = subscription_fields_from_event(_event(current_period_end=None))

    assert "current_period_end" not in fields
