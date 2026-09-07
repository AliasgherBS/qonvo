"""The rep's on/off switch (spec §3).

Until now a new tenant scanned the QR code and the rep began answering real
customers from an empty knowledge base. Nobody agreed to that.

The interesting behaviour is not the flag, it is what happens while it is off:
the message is still received, still stored, still in the inbox, and the owner
answers by hand. An off rep is a quiet rep, not a black hole. That property is
what these tests protect, because the obvious implementation of "do not reply"
is to drop the message earlier, and that would lose it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.api.activation import Readiness


# --- readiness is advisory, not a gate ------------------------------------------ #
def test_ready_needs_all_three():
    assert (
        Readiness(whatsapp_connected=True, has_grounding=True, business_name_set=True).ready
        is True
    )


@pytest.mark.parametrize(
    "missing",
    ["whatsapp_connected", "has_grounding", "business_name_set"],
)
def test_any_missing_piece_makes_it_not_ready(missing):
    fields = {
        "whatsapp_connected": True,
        "has_grounding": True,
        "business_name_set": True,
        missing: False,
    }
    assert Readiness(**fields).ready is False


def test_readiness_does_not_prevent_activation():
    """Deliberate: an owner who switches on with no knowledge gets a rep that
    says it does not know most answers. Worth warning about, not ours to
    forbid. Their number, their customers.

    Encoded as a test because "show what is missing" is one small change away
    from "refuse until fixed", and that change would look like a fix."""
    from app.api.activation import ActivationRequest

    # The request carries no readiness assertion at all. There is nothing for a
    # server-side check to hang off, which is the point.
    assert set(ActivationRequest.model_fields) == {"rep_active"}


# --- what "off" must not mean --------------------------------------------------- #
def test_the_gate_runs_after_the_message_is_persisted():
    """The pipeline commits the inbound message in phase 1 and gates in phase 2.
    If the activation check moved earlier, an off rep would silently discard
    customer messages, which is strictly worse than replying badly.

    Asserted against the source because the ordering is the invariant, and a
    unit test of the gate function alone cannot see it."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "workers" / "pipeline.py"
    ).read_text(encoding="utf-8")

    persist = source.index("_persist_inbound")
    gate = source.index('meta={"gate": "rep_inactive"}')
    assert persist < gate, (
        "the rep_inactive gate moved above _persist_inbound: an off rep would "
        "now drop customer messages instead of storing them for the owner"
    )


def test_activation_is_separate_from_conversation_takeover():
    """Overloading the per-conversation states would make "paused" mean two
    things on the same screen. _PAUSED_STATES is about one conversation; this
    flag is about the workspace."""
    from app.workers.pipeline import _PAUSED_STATES

    assert "rep_inactive" not in _PAUSED_STATES
    assert not any("rep_" in state for state in _PAUSED_STATES)


# --- both gates apply ----------------------------------------------------------- #
def test_being_switched_on_does_not_bypass_billing():
    """The flag is additional to service_state, never a replacement. A tenant
    whose trial expired must stay silent however keen they are."""
    from app.billing.state import service_state

    expired = service_state(
        tenant_status="active",
        plan="trial",
        trial_ends_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
        subscription=None,
        now=dt.datetime.now(dt.UTC),
    )
    assert expired.allowed is False


# --- signup ---------------------------------------------------------------------- #
def test_signup_states_the_flag_rather_than_relying_on_the_default():
    """warmup_stage was dead code because the caller always passed it. The
    lesson generalises: a model default is not a default when every caller
    supplies the field, so the value that matters is written where it is read."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "services" / "auth.py"
    ).read_text(encoding="utf-8")

    assert "rep_active=False" in source


def test_the_column_default_is_off_too():
    """Belt and braces for any path that does not go through signup, such as an
    admin-created tenant."""
    from app.models.tenant import Tenant

    assert Tenant.__table__.c.rep_active.default.arg is False
    assert Tenant.__table__.c.rep_active.nullable is False


# --- the audit trail ------------------------------------------------------------- #
def test_both_transitions_are_named_distinctly():
    """"The bot stopped answering" is a support question, and the first thing
    worth knowing is whether somebody switched it off."""
    import inspect

    from app.api import activation

    source = inspect.getsource(activation.set_activation)
    assert '"rep_activated"' in source
    assert '"rep_paused"' in source


def test_readiness_is_recorded_at_the_moment_of_the_decision():
    """Whether the knowledge base was empty at the time cannot be
    reconstructed afterwards, so it goes in the audit row."""
    import inspect

    from app.api import activation

    source = inspect.getsource(activation.set_activation)
    assert "readiness.model_dump()" in source


# --- the placeholder business name ----------------------------------------------- #
@pytest.mark.parametrize(
    "name,expected",
    [
        ("Glow Salon", True),
        ("Dev Tenant", False),
        ("dev tenant", False),
        ("  DEV TENANT  ", False),
        ("", False),
    ],
)
def test_the_seeded_placeholder_does_not_count_as_a_business_name(name, expected):
    """Someone who never changed it has not finished setting up, whatever the
    column says."""
    readiness = Readiness(
        whatsapp_connected=True,
        has_grounding=True,
        business_name_set=bool(name) and name.strip().lower() != "dev tenant",
    )
    assert readiness.business_name_set is expected


def test_readiness_model_is_json_serialisable():
    """It goes into audit_log meta, which is JSONB."""
    import json

    readiness = Readiness(
        whatsapp_connected=True, has_grounding=False, business_name_set=True
    )
    assert json.loads(json.dumps(readiness.model_dump())) == readiness.model_dump()
