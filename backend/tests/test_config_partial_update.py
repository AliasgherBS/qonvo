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
