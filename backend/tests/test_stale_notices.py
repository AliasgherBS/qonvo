"""A notice whose basis was corrected afterwards (functional test F6).

Two "Voice replies are paused" rows are in production, an hour apart, sent by a
dedupe that tested a marker nothing ever wrote. Then the meter they were derived
from was corrected downward: it reads 2 minutes of 5, so voice was never
exhausted and voice replies never stopped. The notices are simply wrong, and
nothing in the product reconciled them.

The chosen answer is to supersede rather than delete, and to derive it rather
than store it. These tests pin both halves: the retraction appears while the
premise is false, and disappears the moment the premise is true again -- which
is the property a stored flag would not have had.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.agent import voice_allowance as va
from app.agent.voice_allowance import VOICE_QUOTA_NOTIFICATION_TITLE, VoiceAllowance
from app.services.notifications import stale_reasons

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC)
TENANT = uuid.uuid4()


class _Row:
    """Enough Notification to be judged: an id, a title and a timestamp."""

    def __init__(self, title: str, created_at: dt.datetime) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.created_at = created_at


def _voice_notice(created_at: dt.datetime = NOW - dt.timedelta(hours=17)) -> _Row:
    return _Row(VOICE_QUOTA_NOTIFICATION_TITLE, created_at)


@pytest.fixture
def allowance(monkeypatch):
    """Set what the meter now says, and count how often it is consulted."""
    state = {"calls": 0, "used": 89, "allowed": 300}

    async def fake(db, tenant_id, *, now=None, tenant_config=None):  # noqa: ANN001
        state["calls"] += 1
        return VoiceAllowance(
            used_seconds=state["used"], allowed_seconds=state["allowed"]
        )

    monkeypatch.setattr(va, "voice_allowance", fake)
    return state


async def test_the_two_production_rows_are_retracted(allowance):
    """89 seconds of 300 is not an exhausted allowance, so a notice saying the
    voice minutes ran out does not hold, and says so in its own words."""
    rows = [_voice_notice(), _voice_notice(NOW - dt.timedelta(hours=18))]

    reasons = await stale_reasons(None, TENANT, rows, now=NOW)

    assert set(reasons) == {rows[0].id, rows[1].id}
    reason = reasons[rows[0].id]
    assert "No longer applies" in reason
    # Both granularities, because the minutes are rounded up and an owner
    # comparing them with an operator's screen needs the stored figure (F7).
    assert "2 of 5 voice minutes" in reason
    assert "89 of 300 seconds" in reason


async def test_a_notice_that_is_true_again_is_not_retracted(allowance):
    """The reason for deriving this rather than storing a flag: if the tenant
    really does run out later this period, the same row is accurate again."""
    allowance["used"] = 300
    reasons = await stale_reasons(None, TENANT, [_voice_notice()], now=NOW)
    assert reasons == {}


async def test_a_closed_month_is_left_alone(allowance):
    """It was true when it was sent, against a meter that has since reset.
    Re-judging it against this month's usage would be a new kind of wrong."""
    last_month = _voice_notice(dt.datetime(2026, 8, 20, tzinfo=dt.UTC))
    assert await stale_reasons(None, TENANT, [last_month], now=NOW) == {}


async def test_unrelated_notifications_are_untouched(allowance):
    rows = [_Row("A customer needs a human", NOW), _Row("Booking confirmed", NOW)]
    assert await stale_reasons(None, TENANT, rows, now=NOW) == {}


async def test_the_common_case_costs_no_query(allowance):
    """The bell polls every 30s for every tenant. A tenant with no such notice
    must not pay for an aggregate over usage_counters to find that out."""
    await stale_reasons(None, TENANT, [_Row("A customer needs a human", NOW)], now=NOW)
    assert allowance["calls"] == 0

    await stale_reasons(None, TENANT, [_voice_notice()], now=NOW)
    assert allowance["calls"] == 1


async def test_a_naive_timestamp_does_not_crash_the_bell(allowance):
    """``created_at`` is timestamptz in Postgres, but nothing stops a caller
    handing over a naive datetime, and an exception here would take out the
    whole notification list."""
    rows = [_voice_notice(dt.datetime(2026, 9, 8, 19, 14))]
    assert len(await stale_reasons(None, TENANT, rows, now=NOW)) == 1
