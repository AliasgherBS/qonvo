"""Billing provider adapters and event normalisation (billing design §3.4).

The point of these tests is that the route and the reconciler never learn any
provider's vocabulary: adapters translate into ``BillingEvent``, and everything
downstream sees only that.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.billing.providers.base import BillingEvent, Checkout, InvalidWebhookSignature
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
    """Nothing signs manual events, so nothing arriving there can be shown to
    be authentic.

    It raises rather than returning None, because None now means "verified but
    not actionable" and the route answers 200 to that. The manual adapter
    cannot make the "verified" half of that claim about anything."""
    with pytest.raises(InvalidWebhookSignature):
        ManualProvider().parse_event({}, b"{}")


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


# --- 401 vs 200: what the route does with each ---------------------------------- #
# The distinction is operational, and it is the whole reason InvalidWebhookSignature
# exists. Providers send far more event types than any integration uses, so
# "authentic but not interesting" is the common case. Answering an error to it
# gets the endpoint disabled for repeated failures, and then billing stops with
# nothing on fire.
#
# A bad signature has to stay loud, though: 200 there would make a wrong signing
# secret look like a working integration in the provider's delivery log.
def test_the_route_separates_cannot_verify_from_not_actionable():
    import inspect

    from app.api import billing_webhooks

    source = inspect.getsource(billing_webhooks.billing_webhook)

    # A signature failure is the only 401.
    assert "except InvalidWebhookSignature" in source
    assert source.index("except InvalidWebhookSignature") < source.index("HTTP_401_UNAUTHORIZED")

    # An authentic-but-unhandled event answers 200 with a reason.
    not_actionable = source.index('"not_actionable"')
    assert source.count("HTTP_401_UNAUTHORIZED") == 1
    assert "HTTP_401" not in source[not_actionable - 300 : not_actionable]


def test_an_unknown_subscription_and_an_unhandled_event_agree():
    """These used to contradict each other: an unknown subscription answered
    200 with a comment explaining that retries would not help, while an
    unhandled event answered 401 two lines above it."""
    import inspect

    from app.api import billing_webhooks

    source = inspect.getsource(billing_webhooks.billing_webhook)

    assert '"unknown_subscription"' in source
    assert '"not_actionable"' in source
    # Neither sets a status code, so both fall through to 200.
    for reason in ('"unknown_subscription"', '"not_actionable"'):
        window = source[max(0, source.index(reason) - 400) : source.index(reason)]
        assert "response.status_code" not in window, reason


# --- prices come from the provider, never from our own table ---------------- #
#
# The 3 October production audit found the Polar checkout page promising 20
# voice minutes on a plan that grants 180, and describing Growth's allowances
# on the $60 Scale product. Both were copies of a number that had moved. The
# lesson these tests encode is that there must be exactly one place a price
# lives, and it is not this repository.


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _polar(monkeypatch, *, price_map, responses, token="polar_oat_test"):
    from app.billing.providers import polar as polar_mod

    monkeypatch.setattr(polar_mod.settings, "polar_access_token", token)
    monkeypatch.setattr(polar_mod.settings, "billing_price_map", price_map)
    monkeypatch.setattr(polar_mod.settings, "polar_server", "sandbox")
    monkeypatch.setattr(polar_mod.PolarProvider, "_price_cache", None)

    def fake_get(url, **_kwargs):
        product_id = url.rsplit("/", 1)[-1]
        if product_id not in responses:
            return _FakeResponse({}, status_code=404)
        return _FakeResponse(responses[product_id])

    monkeypatch.setattr(polar_mod.httpx, "get", fake_get)
    return polar_mod.PolarProvider()


def test_plan_prices_are_read_from_the_provider(monkeypatch):
    provider = _polar(
        monkeypatch,
        price_map={"prod_a": "starter", "prod_b": "growth"},
        responses={
            "prod_a": {"prices": [{"price_amount": 1000, "price_currency": "USD",
                                   "recurring_interval": "month"}]},
            "prod_b": {"prices": [{"price_amount": 2000, "price_currency": "USD",
                                   "recurring_interval": "month"}]},
        },
    )
    prices = provider.plan_prices()
    assert prices["starter"].amount == 1000
    assert prices["growth"].amount == 2000
    # Minor units, the way every gateway quotes them, and lowercased currency so
    # the page never has to care which case the provider used.
    assert prices["growth"].currency == "usd"
    assert prices["growth"].interval == "month"


def test_a_plan_the_provider_cannot_price_is_absent_rather_than_zero(monkeypatch):
    """A missing price must not render as free."""
    provider = _polar(
        monkeypatch,
        price_map={"prod_a": "starter", "prod_missing": "scale"},
        responses={"prod_a": {"prices": [{"price_amount": 1000, "price_currency": "usd"}]}},
    )
    prices = provider.plan_prices()
    assert "starter" in prices
    assert "scale" not in prices


def test_a_provider_outage_leaves_the_page_renderable(monkeypatch):
    """No price is a quiet page. An exception would be a 500 on the upgrade path."""
    from app.billing.providers import polar as polar_mod

    provider = _polar(monkeypatch, price_map={"prod_a": "starter"}, responses={})

    def boom(*_a, **_k):
        raise RuntimeError("polar is down")

    monkeypatch.setattr(polar_mod.httpx, "get", boom)
    assert provider.plan_prices() == {}


def test_an_outage_is_not_cached_over_a_good_result(monkeypatch):
    """Caching {} after a blip would hide every price for the whole TTL."""
    from app.billing.providers import polar as polar_mod

    provider = _polar(
        monkeypatch,
        price_map={"prod_a": "starter"},
        responses={"prod_a": {"prices": [{"price_amount": 1000, "price_currency": "usd"}]}},
    )
    assert provider.plan_prices()["starter"].amount == 1000

    monkeypatch.setattr(polar_mod.PolarProvider, "_price_cache", None)

    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(polar_mod.httpx, "get", boom)
    assert provider.plan_prices() == {}
    # and nothing empty was written to the cache
    assert polar_mod.PolarProvider._price_cache is None


def test_without_a_token_no_provider_call_is_attempted(monkeypatch):
    from app.billing.providers import polar as polar_mod

    provider = _polar(monkeypatch, price_map={"prod_a": "starter"}, responses={}, token=None)

    def boom(*_a, **_k):
        raise AssertionError("should not have called the provider")

    monkeypatch.setattr(polar_mod.httpx, "get", boom)
    assert provider.plan_prices() == {}


def test_the_manual_provider_states_no_price():
    assert ManualProvider().plan_prices() == {}


# --- a failed billing call must not answer 200 ------------------------------ #
#
# Finding L3, 11 September: change-plan, cancel and resume all answered 200 with
# {"ok": false}, so a client checking the status code believed the plan changed.


def test_a_refusal_carries_a_failure_status_and_keeps_its_body():
    from app.api.billing import _billing_result

    nothing_to_cancel = _billing_result(False, "no_subscription")
    assert nothing_to_cancel.status_code == 409

    upstream_down = _billing_result(False, "provider_unavailable")
    assert upstream_down.status_code == 502

    import json

    assert json.loads(nothing_to_cancel.body) == {"ok": False, "reason": "no_subscription"}


def test_success_is_still_a_200():
    from app.api.billing import _billing_result

    assert _billing_result(True, None).status_code == 200


def test_an_unrecognised_reason_still_fails_rather_than_passing():
    from app.api.billing import _billing_result

    assert _billing_result(False, "something_new").status_code == 409
