"""The plan-upgrade confirmation (spec §7, follow-up).

Deliberately not a receipt. Qonvo sells through a merchant of record, so the
provider is the seller of record: it collects the tax, issues the invoice, and
emails its own confirmation with a portal link to download both. A second
document for one sale would be wrong rather than merely redundant.

What the provider's receipt cannot say is anything about the product. It says a
business paid $18; it cannot say their allowance went from 300 messages to
5,000. That gap is what this email fills, which is why every number in it comes
from the plan catalogue.

The other half of these tests is about firing exactly once. The live sandbox
payment produced **four** events, so the naive wiring sends four emails.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from app.api import billing_webhooks as W
from app.billing.plans import PLANS, TRIAL_PLAN
from app.services import email_templates as T

#: The four events one real payment produced, in the order Polar sent them.
LIVE_SEQUENCE = [
    "subscription.created",
    "subscription.active",
    "subscription.updated",
    "order.paid",
]


def _code(func) -> str:
    """A function's source with comments and its docstring removed.

    Both of the assertions below are about what the code *does*, and a naive
    grep of the source matched the prose instead: the docstrings here discuss
    the very strings being forbidden. ast.unparse drops comments, and popping
    the docstring node drops the rest.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        node.body = body[1:]
    return ast.unparse(tree)


def _rendered(**overrides):
    kwargs = {
        "business": "Glow Salon",
        "plan_name": "Growth",
        "plan_key": "growth",
        "dashboard_url": "https://qonvo.org",
        "amount_cents": 1800,
        "currency": "usd",
        "invoice_number": "QONVO-VXXDURBXHE-0001",
    }
    return T.plan_upgraded(**{**kwargs, **overrides})


# --- fires once ------------------------------------------------------------------ #
def test_only_the_payment_event_sends_it():
    """Four events, one email. Any other choice sends four, and order.paid is
    the only one that knows money moved or what was charged."""
    code = _code(W._confirm_upgrade_by_email)

    assert "event.type != 'order.paid'" in code
    for other in LIVE_SEQUENCE[:-1]:
        assert other not in code, f"{other} would also trigger the email"


def test_a_renewal_is_silent():
    """Telling someone monthly that their card worked is noise the provider's
    own receipt already covers. The interesting thing here is a change of
    allowance, and a renewal is not one."""
    code = _code(W._confirm_upgrade_by_email)

    assert "event.billing_reason != 'subscription_create'" in code


def test_it_runs_after_the_idempotency_ledger_has_already_returned():
    """record_event turns a provider retry into a duplicate and returns early.
    Sending before that point emails again on every retry, and merchants of
    record retry."""
    source = inspect.getsource(W.billing_webhook)

    duplicate = source.index('"duplicate"')
    send = source.index("_confirm_upgrade_by_email")
    assert duplicate < send


def test_it_runs_after_the_commit_not_inside_it():
    """The opposite of the usual rule in this codebase, and deliberate: a failed
    send must not roll back a payment that has already been applied."""
    source = inspect.getsource(W.billing_webhook)

    assert source.index("db.commit()") < source.index("_confirm_upgrade_by_email")


def test_an_unresolvable_plan_sends_nothing():
    """Better silent than a confirmation naming the wrong allowances."""
    code = _code(W._confirm_upgrade_by_email)

    assert "not event.plan_key" in code


# --- says what the receipt cannot ------------------------------------------------ #
def test_the_numbers_come_from_the_catalogue():
    """Not typed here. An email promising an allowance nobody sells would be
    plans.py failing at its only job."""
    _, text, html = _rendered()
    growth = PLANS["growth"].entitlements

    for value in (
        f"{growth['monthly_message_quota']:,}",
        str(growth["monthly_voice_minutes"]),
        str(growth["seats"]),
        str(growth["knowledge_sources"]),
    ):
        assert value in text, value
        assert value in html, value


def test_it_names_what_they_had_before_so_the_change_is_legible():
    """"5,000 messages" is a number. "5,000, up from 300" is an upgrade."""
    _, text, _ = _rendered()
    trial = PLANS[TRIAL_PLAN].entitlements["monthly_message_quota"]

    assert f"up from the trial's {trial:,}" in text


def test_it_does_not_narrate_the_payment_provider_at_the_customer():
    """An earlier draft explained that the receipt would arrive separately from
    Polar. It read as a company distancing itself from its own invoice, and it
    was not reliably true either: Polar generates the invoice document only on
    request, so a customer told to wait for one might wait forever.

    Naming the plumbing is our problem to hide, not theirs to understand."""
    _, text, html = _rendered()

    for content in (text, html):
        assert "Polar" not in content
        assert "payment provider" not in content.lower()


def test_it_points_at_the_billing_page_for_the_history():
    """Somewhere to go, rather than something to wait for. The billing page has
    the full history and the link into the provider's portal, so one
    destination answers "where is my receipt" and "how do I cancel"."""
    _, text, html = _rendered()

    assert "https://qonvo.org/billing" in text
    assert "https://qonvo.org/billing" in html
    assert "payment history" in text.lower()


def test_the_amount_is_quoted_from_the_event_not_from_a_price_list():
    """Prices live with the merchant of record and never in this repo. Quoting
    what a customer was actually charged, as the provider reported it, is a
    different thing."""
    _, text, _ = _rendered(amount_cents=1800, currency="usd")
    assert "USD 18.00" in text

    # No hardcoded plan price in the template's code.
    code = _code(T.plan_upgraded)
    for price in ("10.00", "18.00", "30.00", "$10", "$18", "$30"):
        assert price not in code, f"a price leaked into the template: {price}"


def test_it_works_when_the_provider_reports_no_amount():
    """A fully discounted order, or a provider that omits it. The email must
    still be sendable without inventing a figure."""
    _, text, html = _rendered(amount_cents=None, currency=None, invoice_number=None)

    assert "Charged" not in text
    assert "Invoice:" not in text
    assert "5,000" in text  # the useful half survives


def test_a_zero_amount_is_reported_rather_than_dropped():
    """0 is a real amount. Treating it as missing would silently hide a fully
    discounted order from its own confirmation."""
    _, text, _ = _rendered(amount_cents=0, currency="usd")

    assert "USD 0.00" in text


# --- consistent with the other four ----------------------------------------------- #
BRAND = {
    "Signal Green": "#00C776",
    "Volt": "#C6FF3D",
    "Deep Forest": "#0B3B2B",
    "Ink": "#08130E",
    "Paper": "#F3EFE6",
}


@pytest.mark.parametrize("name,hex_value", list(BRAND.items()))
def test_it_uses_the_same_palette_as_the_others(name, hex_value):
    _, _, html = _rendered()
    if name == "Volt":
        assert html.count(hex_value) <= 1  # a spotlight, not a background
    else:
        assert hex_value in html, name


def test_no_em_dashes_and_no_remote_images():
    _, _, html = _rendered()

    assert "—" not in html
    assert "–" not in html
    assert "<img" not in html
    assert "<style" not in html
