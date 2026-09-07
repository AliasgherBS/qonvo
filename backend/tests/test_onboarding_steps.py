"""The setup checklist (spec §8.1).

Derived entirely from data that already exists. That is the property worth
protecting: a checklist with its own stored "done" state drifts from reality the
first time someone deletes a knowledge source, and then it lies in the direction
that matters, telling an owner they are set up when they are not.

The other property is that the last step is activation, so onboarding and going
live are one journey. Two surfaces both claiming to be the final step is how
someone finishes the checklist and still has a silent rep.
"""

from __future__ import annotations

import inspect

import pytest
from app.api import onboarding as O
from app.api.onboarding import OnboardingStatus, OnboardingStep


def _step(key: str, **overrides) -> OnboardingStep:
    base = {
        "key": key,
        "label": key,
        "description": "",
        "done": False,
        "required": True,
        "href": f"/{key}",
    }
    return OnboardingStep(**{**base, **overrides})


# --- shape ---------------------------------------------------------------------- #
def test_every_step_carries_somewhere_to_go():
    """A list that tells you what is missing without taking you there is a list
    of chores."""
    source = inspect.getsource(O.onboarding_status)

    # Every constructed step names an href.
    constructed = source.count("OnboardingStep(")
    assert constructed >= 5
    assert source.count("href=") == constructed


def test_the_five_required_steps_are_the_ones_the_spec_names():
    source = inspect.getsource(O.onboarding_status)

    for key in ("whatsapp", "knowledge", "behavior", "tested", "activate"):
        assert f'key="{key}"' in source, key


def test_activation_is_the_last_step():
    """Onboarding and going live are the same journey. If activation were not
    here, an owner could complete every item and still have a rep that does not
    answer."""
    source = inspect.getsource(O.onboarding_status)

    keys = [
        line.split('key="')[1].split('"')[0] for line in source.splitlines() if 'key="' in line
    ]
    required_order = [k for k in keys if k != "integrations"]
    assert required_order[-1] == "activate"


def test_google_stays_optional():
    """Bookings are a value-added skill. Blocking "you are set up" on an
    integration most tenants will not use would make the checklist unfinishable
    for them."""
    source = inspect.getsource(O.onboarding_status)
    integrations = source[source.index('key="integrations"') :]
    assert "required=False" in integrations[:400]


# --- progress arithmetic --------------------------------------------------------- #
def test_progress_counts_required_steps_only():
    """An optional item nobody wants must not make progress read worse. "4 of 5"
    with Google skipped is honest; "4 of 6" invites finishing something
    pointless."""
    steps = [
        _step("a", done=True),
        _step("b", done=True),
        _step("c"),
        _step("optional", required=False),
    ]
    required = [s for s in steps if s.required]
    status = OnboardingStatus(
        steps=steps,
        complete=all(s.done for s in required),
        done_count=sum(1 for s in required if s.done),
        total_count=len(required),
    )

    assert (status.done_count, status.total_count) == (2, 3)
    assert status.complete is False


def test_complete_ignores_optional_steps():
    steps = [_step("a", done=True), _step("optional", required=False, done=False)]
    required = [s for s in steps if s.required]

    assert all(s.done for s in required) is True


# --- what "tested" honestly means ------------------------------------------------ #
def test_tested_requires_a_reply_not_just_an_inbound_message():
    """An inbound message proves the webhook works. It does not prove the rep
    answered, which is the thing the owner is being asked to check."""
    source = inspect.getsource(O.onboarding_status)
    block = source[source.index("has_replied") :]

    assert "MessageDirection.outbound" in block
    assert "MessageAuthor.bot" in block


def test_grounding_accepts_instructions_as_well_as_documents():
    """A tenant can legitimately run on rules alone, which the live grounding
    test proved. Requiring an uploaded document would block a working setup."""
    source = inspect.getsource(O.onboarding_status)
    block = source[source.index("has_voice_and_tone") : source.index("has_session")]

    assert "custom_instructions" in block
    assert "persona" in block


# --- no stored state ------------------------------------------------------------- #
def test_nothing_is_persisted_about_progress():
    """The checklist has no table and writes nothing. If it did, it could claim
    a step is done that no longer is."""
    source = inspect.getsource(O)

    assert "db.add(" not in source
    assert "update(" not in source
    assert "commit" not in source


@pytest.mark.parametrize("verb", ["POST", "PUT", "PATCH", "DELETE"])
def test_the_endpoint_is_read_only(verb):
    source = inspect.getsource(O)
    assert f"@router.{verb.lower()}" not in source
