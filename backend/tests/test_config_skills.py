"""The skill list an owner sees must agree with the tools the model gets (P1).

The Skills page named none of the eight things the rep can do, so an owner
could not see what they bought, and could not tell which of it was waiting on a
Google connection they had never made.

The risk in fixing that by rendering a list is drift: a page that says "Book an
appointment: active" while ``enabled_skill_names`` never offers the tool is
worse than no page. So the availability rule is asserted here against the same
inputs the registry uses, and the copy is asserted to cover the registry rather
than a hand-written list of eight.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.config import SKILL_COPY, skill_states
from app.skills.registry import SKILL_REGISTRY


def _defs(**overrides):
    """A tiny registry-shaped map, so the rule is tested without the real one."""
    return {
        name: SimpleNamespace(
            description=f"{name} description",
            requires_integration=overrides.get(name, (None, None))[0],
            requires_config_key=overrides.get(name, (None, None))[1],
        )
        for name in overrides
    }


def test_an_ungated_skill_is_available():
    rows = skill_states(
        _defs(capture_lead=(None, None)),
        ready=set(),
        config_row=SimpleNamespace(),
        configured={},
    )
    assert [(r.key, r.available, r.needs) for r in rows] == [("capture_lead", True, None)]


def test_an_integration_gate_says_what_to_connect():
    definitions = _defs(book_appointment=("google_calendar", None))

    blocked = skill_states(
        definitions, ready=set(), config_row=SimpleNamespace(), configured={}
    )[0]
    assert blocked.available is False
    assert blocked.needs == "Connect Google Calendar"

    ready = skill_states(
        definitions, ready={"google_calendar"}, config_row=SimpleNamespace(), configured={}
    )[0]
    assert ready.available is True
    assert ready.needs is None


def test_a_config_gate_reads_the_tenant_config():
    definitions = _defs(share_payment_details=(None, "payment_details"))

    blocked = skill_states(
        definitions, ready=set(), config_row=SimpleNamespace(payment_details=None), configured={}
    )[0]
    assert blocked.needs == "Add your payment details"

    filled = skill_states(
        definitions,
        ready=set(),
        config_row=SimpleNamespace(payment_details="IBAN 123"),
        configured={},
    )[0]
    assert filled.available is True


def test_an_explicit_disabled_row_wins_over_a_satisfied_gate():
    """``enabled_skill_names`` checks the skills row first; so does this."""
    row = skill_states(
        _defs(book_appointment=("google_calendar", None)),
        ready={"google_calendar"},
        config_row=SimpleNamespace(),
        configured={"book_appointment": False},
    )[0]
    assert row.available is False
    assert row.needs == "Turned off for this workspace"


def test_missing_row_means_enabled():
    """The registry's default is on, so a tenant that never configured a skill
    must not be told it is off."""
    row = skill_states(
        _defs(take_order=(None, None)), ready=set(), config_row=SimpleNamespace(), configured={}
    )[0]
    assert row.available is True


def test_every_registered_skill_has_owner_facing_copy():
    """The page is the only place a skill is ever named to a human, so a skill
    added to the registry without copy would be shown its own model-facing
    prompt text. It still renders, but this is the reminder to write it."""
    assert set(SKILL_COPY) == set(SKILL_REGISTRY)


def test_the_real_registry_renders_with_nothing_connected():
    """The state a brand-new tenant is in: eight rows, none of them missing."""
    rows = skill_states(
        SKILL_REGISTRY,
        ready=set(),
        config_row=SimpleNamespace(payment_details=None),
        configured={},
    )
    assert len(rows) == len(SKILL_REGISTRY)
    # The four Google-gated ones plus payment details are waiting; the rest work
    # on day one, with no setup at all.
    assert {r.key for r in rows if r.available} == {
        "capture_lead",
        "human_handoff",
        "take_order",
    }
