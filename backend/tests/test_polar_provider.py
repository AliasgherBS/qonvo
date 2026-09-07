"""Polar as merchant of record (spec §7).

The signature check is the security boundary: it is the only thing standing
between a stranger and granting themselves the Scale plan. So most of this file
is about the ways a delivery must be rejected, not the happy path.

The signatures below are generated the way Polar generates them rather than
recorded, so these tests fail if the algorithm drifts, not merely if a fixture
goes stale.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from app.billing.providers.base import BillingProvider, InvalidWebhookSignature
from app.billing.providers.polar import (
    TIMESTAMP_TOLERANCE_SECONDS,
    PolarProvider,
)
from app.billing.providers.registry import resolve_billing_provider
from app.core.config import settings

WEBHOOK_ID = "msg_2abc"
RAW_SECRET = "s3cret-signing-key"


def _sign(secret_bytes: bytes, body: bytes, *, webhook_id=WEBHOOK_ID, timestamp=None) -> dict:
    """Build the headers Polar would send. Standard Webhooks:
    base64(HMAC-SHA256(key, "{id}.{timestamp}.{body}")), prefixed "v1,"."""
    timestamp = timestamp or str(int(time.time()))
    signed = b".".join([webhook_id.encode(), timestamp.encode(), body])
    digest = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{digest}",
    }


def _body(event_type: str, **data) -> bytes:
    return json.dumps({"type": event_type, "data": data}).encode()


@pytest.fixture
def polar(monkeypatch):
    monkeypatch.setattr(settings, "polar_webhook_secret", RAW_SECRET)
    monkeypatch.setattr(settings, "billing_price_map", {"price_growth": "growth"})
    return PolarProvider()


# --- the seam ------------------------------------------------------------------- #
def test_it_satisfies_the_provider_protocol():
    """The seam was built with a second implementation to prove it. This is
    the third, and the first with a real gateway behind it."""
    assert isinstance(PolarProvider(), BillingProvider)


def test_it_is_resolvable_by_configuration():
    assert resolve_billing_provider("polar").key == "polar"


# --- signature verification, both schemes --------------------------------------- #
def test_a_raw_utf8_secret_verifies(polar):
    """Polar's pre-8-September-2026 scheme: the secret *is* the HMAC key."""
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body)

    assert polar.parse_event(headers, body) is not None


def test_a_base64_standard_webhooks_secret_verifies(monkeypatch):
    """The post-8-September scheme, where the secret is base64 of the key.

    Both are accepted because asking an operator which side of a date their
    account was created on is a question with a 401 for a wrong answer."""
    key = b"raw-bytes-of-the-key"
    secret = "whsec_" + base64.b64encode(key).decode()
    monkeypatch.setattr(settings, "polar_webhook_secret", secret)
    monkeypatch.setattr(settings, "billing_price_map", {})

    body = _body("subscription.active")
    headers = _sign(key, body)

    assert PolarProvider().parse_event(headers, body) is not None


def test_a_wrong_secret_is_rejected(polar):
    body = _body("subscription.created")
    headers = _sign(b"not-the-secret", body)

    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, body)


def test_a_tampered_body_is_rejected(polar):
    """The signature covers the body, so upgrading yourself by editing the
    payload has to fail."""
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body)

    tampered = body.replace(b"subscription.created", b"subscription.revoked")
    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, tampered)


def test_an_old_delivery_is_rejected_even_with_a_valid_signature(polar):
    """A captured request would otherwise be useful forever."""
    old = str(int(time.time()) - TIMESTAMP_TOLERANCE_SECONDS - 60)
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body, timestamp=old)

    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, body)


def test_a_future_timestamp_is_rejected_too(polar):
    """The tolerance is absolute. A clock-skewed forgery is still a forgery."""
    future = str(int(time.time()) + TIMESTAMP_TOLERANCE_SECONDS + 60)
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body, timestamp=future)

    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, body)


@pytest.mark.parametrize("missing", ["webhook-id", "webhook-timestamp", "webhook-signature"])
def test_a_missing_header_is_rejected(polar, missing):
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body)
    headers.pop(missing)

    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, body)


def test_no_configured_secret_means_nothing_is_authentic(monkeypatch):
    """Failing closed is the difference between "billing is not set up" and
    "anyone can grant themselves a plan"."""
    monkeypatch.setattr(settings, "polar_webhook_secret", None)
    monkeypatch.setattr(settings, "billing_webhook_secret", None)

    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body)

    with pytest.raises(InvalidWebhookSignature):
        PolarProvider().parse_event(headers, body)


def test_rotation_works_because_any_signature_may_match(polar):
    """During a rotation Polar sends several space-separated signatures. If we
    required the first to match, every delivery would fail mid-rotation."""
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body)
    good = headers["webhook-signature"]
    headers["webhook-signature"] = f"v1,{base64.b64encode(b'old').decode()} {good}"

    assert polar.parse_event(headers, body) is not None


def test_an_unknown_signature_version_is_ignored_not_trusted(polar):
    body = _body("subscription.created")
    headers = _sign(RAW_SECRET.encode(), body)
    headers["webhook-signature"] = headers["webhook-signature"].replace("v1,", "v2,")

    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, body)


def test_malformed_json_with_a_valid_signature_is_still_rejected(polar):
    """In practice this means the endpoint was configured with Polar's Discord
    or Slack format instead of Raw: authentic, and completely unusable."""
    raw = b"{not json"
    headers = _sign(RAW_SECRET.encode(), raw)

    with pytest.raises(InvalidWebhookSignature):
        polar.parse_event(headers, raw)


# --- event mapping --------------------------------------------------------------- #
@pytest.mark.parametrize(
    "event_type,status",
    [
        ("subscription.created", "active"),
        ("subscription.active", "active"),
        ("subscription.uncanceled", "active"),
        ("subscription.cycled", "active"),
        ("subscription.resumed", "active"),
        ("subscription.canceled", "canceled"),
        ("subscription.revoked", "canceled"),
        ("subscription.past_due", "past_due"),
        ("subscription.paused", "paused"),
    ],
)
def test_events_map_onto_states_the_domain_already_understands(polar, event_type, status):
    body = _body(event_type, id="sub_1")
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event is not None
    assert event.status == status


def test_a_scheduled_cancellation_keeps_the_period_end(polar):
    """subscription.canceled means "will end", not "has ended". Dropping the
    period end would cut a paying customer off early, and service_state uses it
    to keep them running to the date they paid for."""
    body = _body(
        "subscription.canceled",
        id="sub_1",
        current_period_end="2026-12-01T00:00:00Z",
    )
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event.status == "canceled"
    assert event.current_period_end is not None
    assert event.current_period_end.tzinfo is not None  # comparable against an aware now


def test_a_payment_failure_asserts_no_plan(polar):
    """It says nothing about which plan the tenant is on, and writing None over
    the plan would erase it. subscription_fields_from_event omits absent fields
    for exactly this reason."""
    body = _body("subscription.past_due", id="sub_1")
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event.status == "past_due"
    assert event.plan_key is None


def test_an_event_we_do_not_act_on_returns_none_rather_than_raising(polar):
    """None means "verified, not actionable", and the route answers 200 to it.
    Raising here would let one extra ticked checkbox in the Polar dashboard get
    the endpoint disabled for repeated errors."""
    body = _body("customer.created", id="cus_1")

    assert polar.parse_event(_sign(RAW_SECRET.encode(), body), body) is None


# --- plan resolution -------------------------------------------------------------- #
@pytest.mark.parametrize(
    "data",
    [
        {"id": "sub_1", "price_id": "price_growth"},
        {"id": "sub_1", "product_id": "price_growth"},
        {"id": "sub_1", "price": {"id": "price_growth"}},
        {"id": "sub_1", "product": {"id": "price_growth"}},
        {"id": "sub_1", "prices": [{"id": "price_growth"}]},
    ],
)
def test_the_plan_is_found_wherever_polar_puts_the_id(polar, data):
    """The payload shape depends on the event, and a missing plan key silently
    leaves a tenant on their old entitlements after an upgrade they paid for."""
    body = _body("subscription.created", **data)
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event.plan_key == "growth"


def test_an_unmapped_price_yields_no_plan_rather_than_a_guess(polar):
    body = _body("subscription.created", id="sub_1", price_id="price_not_ours")
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event.plan_key is None


def test_an_order_event_reads_the_nested_subscription(polar):
    body = _body(
        "order.paid",
        id="ord_1",
        subscription={"id": "sub_9", "price_id": "price_growth"},
    )
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event.subscription_id == "sub_9"
    assert event.plan_key == "growth"


def test_an_order_with_no_subscription_does_not_crash(polar):
    """`data.get("subscription")` is None for a one-off purchase, and every
    field lookup after it would raise."""
    body = _body("order.paid", id="ord_1", subscription=None)
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event is not None
    assert event.subscription_id == "ord_1"  # falls back to the order's own id


# --- idempotency ------------------------------------------------------------------ #
def test_the_event_id_is_the_delivery_id_so_retries_dedupe(polar):
    """Merchants of record retry, and billing_events is the ledger that makes
    that safe. Keying on anything but the delivery id would let a retry apply
    twice."""
    body = _body("subscription.created", id="sub_1")
    event = polar.parse_event(_sign(RAW_SECRET.encode(), body), body)

    assert event.event_id == WEBHOOK_ID


# --- checkout degrades ------------------------------------------------------------ #
def test_checkout_with_no_token_falls_back_to_instructions(monkeypatch):
    """An owner trying to give us money is the worst possible moment to show an
    error page."""
    monkeypatch.setattr(settings, "polar_access_token", None)
    monkeypatch.setattr(settings, "billing_price_map", {"price_growth": "growth"})

    checkout = PolarProvider().checkout(tenant_id="t1", plan_key="growth")

    assert checkout.url is None
    assert checkout.instructions


def test_checkout_for_an_unmapped_plan_says_so(monkeypatch):
    monkeypatch.setattr(settings, "polar_access_token", "polar_oat_x")
    monkeypatch.setattr(settings, "billing_price_map", {})

    checkout = PolarProvider().checkout(tenant_id="t1", plan_key="scale")

    assert checkout.url is None
    assert "scale" in checkout.instructions


def test_a_provider_outage_does_not_500_the_upgrade(monkeypatch):
    monkeypatch.setattr(settings, "polar_access_token", "polar_oat_x")
    monkeypatch.setattr(settings, "billing_price_map", {"price_growth": "growth"})

    def boom(*args, **kwargs):
        raise RuntimeError("polar is down")

    import app.billing.providers.polar as module

    monkeypatch.setattr(module.httpx, "post", boom)

    checkout = PolarProvider().checkout(tenant_id="t1", plan_key="growth")

    assert checkout.url is None
    assert checkout.instructions
