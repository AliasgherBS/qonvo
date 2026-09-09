"""The card on file (teardown Z4).

An expiring card is the largest preventable cause of involuntary churn, and it
is preventable only if the expiry is shown before the renewal fails. So the
things pinned here are the two that make the feature either useful or harmful:
that the *default* card is the one reported, and that anything the provider
cannot answer cleanly becomes None rather than a card the customer does not
recognise.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.billing.providers.base import (
    CARD_EXPIRY_WARNING_DAYS,
    BillingProvider,
    CardOnFile,
)
from app.billing.providers.manual import ManualProvider
from app.billing.providers.polar import PolarProvider
from app.core.config import settings


def _response(items):
    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        @staticmethod
        def json():
            return {"items": items}

    return _R()


def _card(**overrides):
    card = {
        "id": "pm_1",
        "type": "card",
        "customer_id": "cus_1",
        "is_default": True,
        "method_metadata": {
            "brand": "visa",
            "last4": "4242",
            "exp_month": 9,
            "exp_year": 2028,
        },
    }
    card.update(overrides)
    return card


@pytest.fixture
def polar(monkeypatch):
    monkeypatch.setattr(settings, "polar_access_token", "polar_oat_x")
    return PolarProvider()


# --- the seam ------------------------------------------------------------------ #
def test_both_adapters_still_satisfy_the_protocol():
    """The method was added to the protocol, so the manual adapter has to have
    grown it too. That is the point of keeping a second implementation."""
    assert isinstance(PolarProvider(), BillingProvider)
    assert isinstance(ManualProvider(), BillingProvider)


def test_the_manual_adapter_reports_no_card():
    """Nobody entered one: an operator recorded the plan by hand."""
    assert ManualProvider().card_on_file(customer_id="cus_1") is None


# --- reading Polar ------------------------------------------------------------- #
def test_it_reports_brand_last_four_and_expiry(polar, monkeypatch):
    import app.billing.providers.polar as module

    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: _response([_card()]))

    card = polar.card_on_file(customer_id="cus_1")
    assert card == CardOnFile(brand="visa", last4="4242", exp_month=9, exp_year=2028)


def test_the_default_card_wins_over_the_first_one(polar, monkeypatch):
    """The default is the one the renewal is actually charged to. Showing the
    first in the list would name a card that is not being charged, which is
    worse than showing nothing: the owner would update the wrong one."""
    import app.billing.providers.polar as module

    monkeypatch.setattr(
        module.httpx,
        "get",
        lambda *a, **k: _response(
            [
                _card(id="pm_old", is_default=False),
                _card(
                    id="pm_new",
                    is_default=True,
                    method_metadata={
                        "brand": "mastercard",
                        "last4": "5556",
                        "exp_month": 1,
                        "exp_year": 2030,
                    },
                ),
            ]
        ),
    )

    card = polar.card_on_file(customer_id="cus_1")
    assert card is not None
    assert (card.brand, card.last4) == ("mastercard", "5556")


def test_a_wallet_is_carried_through(polar, monkeypatch):
    """Somebody who paid with Apple Pay does not recognise "Visa 4242" as
    theirs, and "update your card" is then the wrong instruction."""
    import app.billing.providers.polar as module

    monkeypatch.setattr(
        module.httpx,
        "get",
        lambda *a, **k: _response(
            [
                _card(
                    method_metadata={
                        "brand": "visa",
                        "last4": "4242",
                        "exp_month": 9,
                        "exp_year": 2028,
                        "wallet": "apple_pay",
                    }
                )
            ]
        ),
    )

    card = polar.card_on_file(customer_id="cus_1")
    assert card is not None and card.wallet == "apple_pay"


@pytest.mark.parametrize(
    "items",
    [
        pytest.param([], id="nothing saved"),
        pytest.param([{"type": "generic", "id": "pm_1"}], id="not a card"),
        pytest.param(
            [_card(method_metadata={"brand": "visa", "last4": "4242"})],
            id="no expiry reported",
        ),
    ],
)
def test_anything_it_cannot_describe_becomes_no_card(polar, monkeypatch, items):
    """Partial metadata cannot answer "is my card about to expire", which is the
    only reason this exists. None leaves the owner a working Update card button
    and no false statement."""
    import app.billing.providers.polar as module

    monkeypatch.setattr(module.httpx, "get", lambda *a, **k: _response(items))

    assert polar.card_on_file(customer_id="cus_1") is None


def test_a_provider_outage_does_not_break_the_page(polar, monkeypatch):
    """Including a 403 from a token without the customers:read scope, which is
    the likely first failure on a real account."""
    import app.billing.providers.polar as module

    def boom(*a, **k):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(module.httpx, "get", boom)

    assert polar.card_on_file(customer_id="cus_1") is None


def test_no_access_token_means_no_card(monkeypatch):
    monkeypatch.setattr(settings, "polar_access_token", None)

    assert PolarProvider().card_on_file(customer_id="cus_1") is None


# --- the expiry window --------------------------------------------------------- #
def _at(year: int, month: int, day: int) -> dt.datetime:
    return dt.datetime(year, month, day, tzinfo=dt.UTC)


def test_a_card_is_valid_to_the_end_of_its_printed_month():
    """09/28 is good through 30 September 2028. Treating the 1st as the expiry
    would call a working card dead for a whole month."""
    card = CardOnFile(brand="visa", last4="4242", exp_month=9, exp_year=2028)

    assert card.expires_after == dt.date(2028, 10, 1)
    assert card.state(now=_at(2028, 9, 30)) != "expired"
    assert card.state(now=_at(2028, 10, 1)) == "expired"


def test_december_rolls_the_year():
    card = CardOnFile(brand="visa", last4="4242", exp_month=12, exp_year=2026)

    assert card.expires_after == dt.date(2027, 1, 1)


def test_the_warning_arrives_before_the_renewal_that_would_fail():
    """Sixty days, so there is time to reach a bank. Outside the window the
    owner is told nothing, because a permanent amber note is not a warning."""
    card = CardOnFile(brand="visa", last4="4242", exp_month=9, exp_year=2028)
    warns_from = card.expires_after - dt.timedelta(days=CARD_EXPIRY_WARNING_DAYS)

    assert card.state(now=_at(warns_from.year, warns_from.month, warns_from.day)) == "expiring"
    day_before = warns_from - dt.timedelta(days=1)
    assert card.state(now=_at(day_before.year, day_before.month, day_before.day)) == "ok"
