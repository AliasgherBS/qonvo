"""The voice allowance meters what we speak, never what we are sent.

The allowance used to bound both legs. It was changed because the two cost
wildly different amounts -- speaking a minute is $0.0135-$0.027, transcribing
one is about $0.003 -- so metering the cheap leg spent the owner's allowance on
the half that barely costs anything, and let a customer's long voice notes
exhaust a budget the business never chose to spend.

Nothing pinned that. The behaviour lived in two lines of the pipeline and was
described in four places, one of which (the billing meter, in front of the
owner) still said "counts voice in both directions" for a release after it had
stopped being true. A comment is not a test: the next person to touch the
metering block has nothing telling them the inbound leg is deliberately free.

So this asserts the split at both ends -- what the writer stores, and what the
gate reads -- because either one alone would let the other drift.
"""

from __future__ import annotations

import datetime as dt
import uuid

from app.agent.voice_allowance import VOICE_MINUTES_KEY, voice_allowance
from app.models.ops import UsageCounter


def test_the_gate_reads_the_outbound_column_only():
    """``voice_allowance`` sums ``voice_seconds``, which is outbound.

    Read off the function rather than mocked: the column it names is the whole
    decision, and a change to the other one would be the bug.
    """
    import inspect

    source = inspect.getsource(voice_allowance)

    assert "UsageCounter.voice_seconds" in source
    assert "voice_seconds_in" not in source, (
        "the gate has started counting inbound audio again; transcription is "
        "deliberately unmetered"
    )


def test_the_pipeline_zeroes_the_metered_total_before_adding_the_reply():
    """The inbound duration is captured and then cleared, not accumulated.

    This is the two-line manoeuvre the whole behaviour rests on. If the reset
    is dropped, the transcribed duration stays in the metered total and every
    tenant silently goes back to being billed for what their customers send.
    """
    import inspect

    from app.workers import pipeline

    source = inspect.getsource(pipeline)

    assert "inbound_voice_seconds = voice_seconds" in source
    assert "voice_seconds = 0" in source, (
        "the metered total is no longer cleared after transcription, so inbound "
        "audio counts against the allowance again"
    )


def test_inbound_seconds_are_still_recorded_somewhere():
    """Unmetered is not the same as unmeasured.

    The analytics page reports average inbound voice length, so the column has
    to keep being written even though nothing gates on it. Deleting it as
    "unused" would take the answer to 'how long is a typical voice note' with
    it.
    """
    assert hasattr(UsageCounter, "voice_seconds_in")


class _Config:
    def __init__(self, minutes: int) -> None:
        self.entitlements = {VOICE_MINUTES_KEY: minutes}


class _Result:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _Db:
    """Returns one number, which is what the gate's single query asks for."""

    def __init__(self, outbound_seconds: int) -> None:
        self.outbound_seconds = outbound_seconds

    async def execute(self, _stmt):  # noqa: ANN001,ARG002 - a stand-in for AsyncSession
        return _Result(self.outbound_seconds)


async def test_a_tenant_who_only_receives_voice_uses_none_of_the_allowance():
    """The case the change exists for, end to end through the gate.

    A customer sends ten minutes of voice notes and the rep answers in text.
    ``voice_seconds`` is therefore zero, and the business still has its whole
    allowance -- which is the promise the billing page now makes.
    """
    allowance = await voice_allowance(
        _Db(outbound_seconds=0),
        tenant_id=uuid.uuid4(),
        now=dt.datetime(2026, 9, 12, tzinfo=dt.UTC),
        tenant_config=_Config(minutes=60),
    )

    assert allowance.used_seconds == 0
    assert allowance.used_minutes == 0
    assert not allowance.exhausted
    assert allowance.remaining_seconds == 3600


async def test_spoken_replies_do_consume_it():
    """The other half, so the test above cannot pass by the gate being broken."""
    allowance = await voice_allowance(
        _Db(outbound_seconds=3600),
        tenant_id=uuid.uuid4(),
        now=dt.datetime(2026, 9, 12, tzinfo=dt.UTC),
        tenant_config=_Config(minutes=60),
    )

    assert allowance.used_minutes == 60
    assert allowance.exhausted


def test_the_owner_facing_copy_does_not_claim_both_directions():
    """The billing meter is where this was wrong in front of a customer.

    Checked here rather than in the dashboard because there is no JS test
    runner in this repo and the claim is about backend behaviour. Precedent:
    tests/test_cost_visibility.py.
    """
    from pathlib import Path

    zone = (
        Path(__file__).resolve().parents[2]
        / "dashboard"
        / "components"
        / "billing"
        / "usage-zone.tsx"
    )
    text = zone.read_text()

    assert "both directions" not in text, (
        "the billing meter tells the owner voice counts both ways; it counts "
        "only what the rep speaks"
    )
