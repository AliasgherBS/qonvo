"""Where a business's invoices go (teardown Z7).

Billing notices went to the address that happened to sign up. In a business of
any size that is a founder or an office manager and not the person who pays
invoices, so the one email that must reach accounts payable was the one email
that could not be redirected.

``tenant_config.billing_email`` is that redirect. Empty means "use the owner's
login address", which is both the default and the old behaviour, so the
fallback is load-bearing rather than a nicety: a tenant that never touches the
field must keep receiving its invoices.

The other half of the decision is what is deliberately *not* here. No tax id,
no company registration, no invoice address. The merchant of record is the
seller named on the invoice and issues it under its own registration, so which
of those apply is its question. A field we collect and never print on anything
looks like a feature and behaves like a dead end.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.api.config import (
    ConfigResponse,
    ConfigUpdateRequest,
    _apply_config_update,
    _config_to_dict,
    normalise_billing_email,
)
from app.services import email as E
from fastapi import HTTPException


def _stored(**overrides) -> SimpleNamespace:
    """A config row as it sits in the database."""
    row = SimpleNamespace(
        version=1,
        persona="friendly",
        business_name="Glow Salon",
        primary_language="en",
        tone="warm",
        custom_instructions="Never quote a price.",
        languages=["en"],
        providers={},
        timezone="Asia/Karachi",
        business_hours={"enabled": True},
        escalation_rules={"notify_on_handoff": True},
        owner_alert_number="+923194505305",
        llm_provider="openai",
        llm_model="gpt-5.6-nano",
        payment_details="IBAN 123",
        billing_email=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


# --- the field itself -------------------------------------------------------- #
def test_an_address_is_stored_normalised():
    row = _stored()

    _apply_config_update(row, ConfigUpdateRequest(billing_email="  Accounts@Example.COM  "))

    # Surrounding whitespace is what a paste leaves behind, and the domain is
    # case-insensitive, so one address cannot be stored two ways.
    assert row.billing_email == "Accounts@example.com"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_empty_means_use_the_login_address(value):
    """Cleared, not refused. "Send them to whoever signed up" is a real answer
    and the default one, so it is stored as NULL rather than as an empty
    string the readers would each have to special-case."""
    row = _stored(billing_email="accounts@example.com")

    _apply_config_update(row, ConfigUpdateRequest(billing_email=value))

    assert row.billing_email is None


@pytest.mark.parametrize(
    "value",
    ["accounts", "accounts@", "@example.com", "accounts example.com", "accounts@example"],
)
def test_an_invalid_address_is_refused_with_a_400(value):
    """Refused rather than stored. A billing address that silently never
    delivers is worse than no billing address: the owner would not find out
    from this page, they would find out from a missing invoice, months on."""
    row = _stored()

    with pytest.raises(HTTPException) as exc:
        _apply_config_update(row, ConfigUpdateRequest(billing_email=value))

    assert exc.value.status_code == 400
    assert row.billing_email is None  # nothing written


def test_validation_does_no_dns_lookup():
    """A save must not hang on somebody else's nameserver, and a valid domain
    whose MX is briefly unreachable must not fail the save. Deliverability is
    the provider's problem at send time, not this endpoint's at write time."""
    unresolvable = "accounts@no-such-domain-a7f3c9e1b4.com"

    assert normalise_billing_email(unresolvable) == unresolvable


def test_saving_it_leaves_the_rest_of_the_config_alone():
    """The Billing page sends this one field. Every other page's value has to
    survive that, the same way the Business page's save does."""
    row = _stored()

    _apply_config_update(row, ConfigUpdateRequest(billing_email="accounts@example.com"))

    assert row.llm_model == "gpt-5.6-nano"
    assert row.payment_details == "IBAN 123"
    assert row.business_name == "Glow Salon"


def test_it_is_returned_so_the_page_can_show_what_is_set():
    out = _config_to_dict(_stored(billing_email="accounts@example.com"))

    assert out.billing_email == "accounts@example.com"
    # Unset reads back as null rather than as the owner's address: the empty
    # state is what lets the page say "invoices go to the address you sign in
    # with" instead of pre-filling a value the owner never chose.
    assert _config_to_dict(_stored()).billing_email is None


def test_it_is_audited_by_name_and_not_by_value():
    """PUT /api/config records changed field *names* through audit.record. A
    new field has to flow through that automatically, and the address itself
    must not be copied into the audit row."""
    from app.services.audit import changed_fields

    row = _stored()
    changed = changed_fields(row, {"billing_email": "accounts@example.com"})

    assert changed == ["billing_email"]


# --- deliberately absent ----------------------------------------------------- #
FORBIDDEN = ("tax", "vat", "company_address", "registration", "invoice_address")


@pytest.mark.parametrize("model", [ConfigUpdateRequest, ConfigResponse])
def test_no_tax_or_address_fields_were_added(model):
    """Skipped on purpose, not overlooked. This test is here so that "we
    decided not to collect this" survives the next person who reads the
    teardown finding and assumes it was a to-do list."""
    for field in model.model_fields:
        assert not any(word in field for word in FORBIDDEN), field


def test_the_column_list_is_free_of_them_too():
    from app.models.tenant import TenantConfig

    for column in TenantConfig.__table__.columns:
        assert not any(word in column.name for word in FORBIDDEN), column.name


# --- who the notice is addressed to ------------------------------------------ #
class _Result:
    def __init__(self, rows: list):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    """Answers the three queries the send path makes, by looking at the SQL.

    Dispatching on the statement rather than on call order, because the order
    is an implementation detail of the function under test and a positional
    fake would pass while addressing the email to the wrong person.
    """

    def __init__(self, *, owner_email: str | None, billing_email: str | None, config_row=True):
        self.owner_email = owner_email
        self.billing_email = billing_email
        self.config_row = config_row

    async def execute(self, stmt):
        sql = str(stmt)
        if "tenant_config.billing_email" in sql:
            return _Result([self.billing_email] if self.config_row else [])
        if "tenants.name" in sql:
            rows = [SimpleNamespace(email=self.owner_email, name="Glow Salon")]
            return _Result(rows if self.owner_email else [])
        if "users.email" in sql:
            return _Result([self.owner_email] if self.owner_email else [])
        raise AssertionError(f"unexpected query: {sql}")


TENANT = uuid.uuid4()


async def test_the_billing_address_wins_when_one_is_set():
    db = _FakeDB(owner_email="founder@glow.example", billing_email="accounts@glow.example")

    assert await E.billing_recipient(db, TENANT) == "accounts@glow.example"


@pytest.mark.parametrize("stored", [None, "", "   "])
async def test_it_falls_back_to_the_login_address(stored):
    """The default state, and the previous behaviour. A tenant that never fills
    the field in must keep getting its invoices."""
    db = _FakeDB(owner_email="founder@glow.example", billing_email=stored)

    assert await E.billing_recipient(db, TENANT) == "founder@glow.example"


async def test_a_tenant_with_no_config_row_yet_still_resolves():
    """A freshly created tenant has no tenant_config row at all until something
    writes one, and a first payment can land before anything has."""
    db = _FakeDB(owner_email="founder@glow.example", billing_email=None, config_row=False)

    assert await E.billing_recipient(db, TENANT) == "founder@glow.example"


async def test_the_plan_confirmation_goes_to_the_billing_address(monkeypatch):
    """The test that would have caught the original problem: the one email
    about money was addressed to whoever signed up."""
    sent: list[str] = []

    async def _capture(to, subject, body, html=None, reply_to=None):
        sent.append(to)
        return True

    monkeypatch.setattr(E, "send_email", _capture)
    db = _FakeDB(owner_email="founder@glow.example", billing_email="accounts@glow.example")

    assert await E.send_plan_upgraded_email(db, TENANT, plan_key="growth") is True
    assert sent == ["accounts@glow.example"]


async def test_the_plan_confirmation_still_reaches_an_owner_with_no_billing_address(monkeypatch):
    sent: list[str] = []

    async def _capture(to, subject, body, html=None, reply_to=None):
        sent.append(to)
        return True

    monkeypatch.setattr(E, "send_email", _capture)
    db = _FakeDB(owner_email="founder@glow.example", billing_email=None)

    assert await E.send_plan_upgraded_email(db, TENANT, plan_key="growth") is True
    assert sent == ["founder@glow.example"]


async def test_a_tenant_with_no_owner_sends_nothing(monkeypatch):
    """Unchanged, and worth pinning: the owner lookup is also what proves the
    tenant is real, so losing it to the new lookup would email nobody at an
    address of None."""
    monkeypatch.setattr(E, "send_email", lambda *a, **k: pytest.fail("should not send"))
    db = _FakeDB(owner_email=None, billing_email=None)

    assert await E.send_plan_upgraded_email(db, TENANT, plan_key="growth") is False
