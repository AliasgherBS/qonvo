"""A page that shows part of the config must not clear the rest of it.

Behaviour, Skills and Business each save independently, so every one of them
PUTs a subset. The mechanism that makes this safe is ``exclude_unset=True`` in
``_apply_config_update``: a field the caller never mentioned is absent from the
dump, so the loop never touches the column.

Nothing tested it, and it became load-bearing when the engine picker left the
owner's Business page. That page no longer sends ``llm_provider`` or
``llm_model``, so if an omitted field were ever treated as ``None`` the first
save of a business name would silently wipe a deliberate per-tenant model
override, on the one path nobody would think to check.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.api.config import ConfigUpdateRequest, _apply_config_update
from pydantic import ValidationError


def _stored() -> SimpleNamespace:
    """A config row as it sits in the database, with values worth losing."""
    return SimpleNamespace(
        persona="friendly",
        business_name="Glow Salon",
        primary_language="en",
        tone="warm",
        custom_instructions="Never quote a price.",
        business_hours={"enabled": True},
        owner_alert_number="+923194505305",
        escalation_rules={"notify_on_handoff": True},
        llm_provider="openai",
        llm_model="gpt-5.6-nano",
        payment_details="IBAN 123",
    )


def test_omitted_fields_are_left_alone():
    """The Business page now sends only business_name."""
    row = _stored()

    _apply_config_update(row, ConfigUpdateRequest(business_name="Glow Salon Ltd"))

    assert row.business_name == "Glow Salon Ltd"
    # The engine override survives, which is the whole point.
    assert row.llm_provider == "openai"
    assert row.llm_model == "gpt-5.6-nano"
    # So does everything else no page mentioned.
    assert row.custom_instructions == "Never quote a price."
    assert row.payment_details == "IBAN 123"
    assert row.persona == "friendly"


def test_an_explicit_null_still_clears():
    """Omitted and null must stay different. Admin clearing an override sends
    null on purpose, and that has to keep working."""
    row = _stored()

    _apply_config_update(row, ConfigUpdateRequest(llm_provider=None, llm_model=None))

    assert row.llm_provider is None
    assert row.llm_model is None
    assert row.business_name == "Glow Salon"  # untouched


@pytest.mark.parametrize(
    "field,value",
    [
        ("persona", "formal"),
        ("custom_instructions", "Always greet by name."),
        ("payment_details", "IBAN 999"),
        ("owner_alert_number", "+923000000000"),
    ],
)
def test_each_page_can_save_its_own_field_without_touching_the_engine(field, value):
    row = _stored()

    _apply_config_update(row, ConfigUpdateRequest(**{field: value}))

    assert getattr(row, field) == value
    assert row.llm_provider == "openai"
    assert row.llm_model == "gpt-5.6-nano"


# --------------------------------------------------------------------------- #
# C1 (VPS audit, 2026-09-11): a live tenant lost business_name, persona, tone,
# custom_instructions (1,821 characters of grounding rules) and payment_details
# to a single PUT that returned 200. `exclude_unset` means an explicit null is
# *sent*, so it reached setattr(row, field, None) and the field was gone.
#
# The distinction these tests pin down is override vs content: null clears an
# override on purpose, and must never touch content.
# --------------------------------------------------------------------------- #

DESTRUCTIVE_NULLS = [
    "persona",
    "business_name",
    "tone",
    "custom_instructions",
    "payment_details",
    # These two are NOT NULL columns, so the same request used to reach the
    # database and come back as a 500 rather than an erasure. Same bug.
    "primary_language",
    "timezone",
]


@pytest.mark.parametrize("field", DESTRUCTIVE_NULLS)
def test_null_never_erases_content(field):
    with pytest.raises(ValidationError):
        ConfigUpdateRequest(**{field: None})


@pytest.mark.parametrize("field", ["billing_email", "llm_provider", "llm_model"])
def test_null_still_clears_an_override(field):
    """The other half of the same rule: these are overrides, and absence is a
    state an owner or admin deliberately chooses."""
    assert getattr(ConfigUpdateRequest(**{field: None}), field) is None


def test_an_unknown_field_is_a_422_not_a_silent_200():
    """A misspelled name used to return 200 with an unchanged body, so a caller
    could not tell "you sent nonsense" from "it worked"."""
    with pytest.raises(ValidationError):
        ConfigUpdateRequest(totally_unknown_field="x")


def test_empty_string_is_how_you_deliberately_blank_a_field():
    """Rejecting null has to leave a way to actually clear content."""
    row = _stored()
    _apply_config_update(row, ConfigUpdateRequest(persona=""))
    assert row.persona == ""
    assert row.custom_instructions == "Never quote a price."


# --- the Business page must be savable by a tenant who set nothing ---------- #
#
# Found on production, 3 October 2026, by pressing Save on the Business page
# and watching the network tab. The whole PUT answered 422:
#
#   "null is not how a field is cleared: owner_alert_number, payment_details"
#
# The owner could not change their business name, their timezone or their
# opening hours, because of two fields they had never touched. The page showed
# no error at all: the value simply reverted on reload.
#
# Two fixes collided. The dashboard sends null here deliberately -- a comment in
# lib/api.ts explains that "" used to 422 with "must be digits with an optional
# leading +". The config-erasure fix then made null a 422 as well. Each change
# was correct in isolation and together they locked the page.


def test_an_empty_alert_number_is_accepted_and_means_unset():
    from app.api.config import ConfigUpdateRequest

    body = ConfigUpdateRequest(owner_alert_number="")
    assert body.owner_alert_number is None


def test_whitespace_only_is_the_same_as_empty():
    from app.api.config import ConfigUpdateRequest

    assert ConfigUpdateRequest(owner_alert_number="   ").owner_alert_number is None


def test_a_real_number_still_has_to_look_like_one():
    import pytest
    from app.api.config import ConfigUpdateRequest
    from pydantic import ValidationError

    assert ConfigUpdateRequest(owner_alert_number="+923001234567").owner_alert_number
    with pytest.raises(ValidationError):
        ConfigUpdateRequest(owner_alert_number="not a phone number")


def test_the_whole_business_page_payload_validates_with_everything_empty():
    """The exact shape the page sends for a tenant who has filled nothing in."""
    from app.api.config import ConfigUpdateRequest

    body = ConfigUpdateRequest(
        business_name="test01",
        timezone="Asia/Karachi",
        owner_alert_number="",
        notify_on_handoff=False,
        payment_details="",
    )
    assert body.business_name == "test01"
    assert body.owner_alert_number is None
