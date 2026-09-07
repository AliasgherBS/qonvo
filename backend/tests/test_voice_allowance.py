"""The voice allowance (spec §1).

Voice is 54-74% of per-tenant AI cost and was ungated: any tenant could set
``voice_reply_mode`` to ``always`` and multiply their bill. An unlimited-voice
tenant on the largest plan costs about $54 a month against $30 of revenue.

Two properties matter more than the arithmetic.

**One allowance, both directions.** Speech-to-text is ~30x cheaper than
text-to-speech, so the outbound leg dominates whatever a customer sends.

**Exhaustion degrades.** The rep answers by text. A silent bot is the failure
mode this codebase has been burned by three times, and none of them were worth
a voice note.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.agent.voice_allowance import (
    DEFAULT_VOICE_MINUTES,
    SECONDS_PER_VOICE_MINUTE,
    VOICE_MINUTES_KEY,
    VOICE_QUOTA_NOTICE,
    VoiceAllowance,
    period_start,
)
from app.billing.plans import PLANS, TRIAL_PLAN
from app.core.limits import entitlement


def _allowance(used_seconds: int, minutes: int = 20) -> VoiceAllowance:
    return VoiceAllowance(
        used_seconds=used_seconds, allowed_seconds=minutes * SECONDS_PER_VOICE_MINUTE
    )


# --- the ladder ----------------------------------------------------------------- #
def test_every_plan_has_a_voice_allowance():
    for key, plan in PLANS.items():
        assert VOICE_MINUTES_KEY in plan.entitlements, key


def test_voice_never_shrinks_as_plans_get_bigger():
    ordered = [p for k, p in PLANS.items() if k != TRIAL_PLAN]
    for smaller, larger in zip(ordered, ordered[1:], strict=False):
        assert larger.entitlements[VOICE_MINUTES_KEY] >= smaller.entitlements[VOICE_MINUTES_KEY]


def test_the_ladder_is_the_one_that_was_costed():
    """5/20/100 at $10/$18/$30 leaves 94%/85%/62% gross on the recommended TTS,
    and 51% at Scale on the most expensive Urdu-capable voice. Changing these
    without redoing that arithmetic is how a plan quietly starts losing money."""
    assert PLANS["starter"].entitlements[VOICE_MINUTES_KEY] == 5
    assert PLANS["growth"].entitlements[VOICE_MINUTES_KEY] == 20
    assert PLANS["scale"].entitlements[VOICE_MINUTES_KEY] == 100


@pytest.mark.parametrize("entitlements", [None, {}, {"seats": 2}])
def test_a_tenant_without_the_entitlement_is_capped_not_unlimited(entitlements):
    """These keys are new, so every existing tenant lacks them. Defaulting to
    unlimited would leave the gate off for exactly the population it exists to
    cover: the tenants nobody has looked at."""
    assert entitlement(entitlements, VOICE_MINUTES_KEY, DEFAULT_VOICE_MINUTES) == 5


# --- units ---------------------------------------------------------------------- #
def test_minutes_are_derived_and_never_stored():
    """Seconds are what usage_counters holds and what both legs normalise to.
    Minutes exist only for display, through one constant."""
    assert SECONDS_PER_VOICE_MINUTE == 60
    assert _allowance(used_seconds=600).used_minutes == 10


def test_a_partial_minute_counts_as_used():
    """Rounding down would show 1 minute used while the gate had counted 61
    seconds, so the bar and the behaviour would disagree."""
    assert _allowance(used_seconds=61).used_minutes == 2
    assert _allowance(used_seconds=1).used_minutes == 1
    assert _allowance(used_seconds=0).used_minutes == 0


# --- the gate ------------------------------------------------------------------- #
def test_under_the_allowance_voice_continues():
    assert _allowance(used_seconds=19 * 60).exhausted is False


def test_exactly_at_the_allowance_is_exhausted():
    """20 minutes used of 20 allowed means spent, not one more free reply."""
    assert _allowance(used_seconds=20 * 60).exhausted is True


def test_over_the_allowance_stays_exhausted_without_going_negative():
    over = _allowance(used_seconds=99 * 60)

    assert over.exhausted is True
    assert over.remaining_seconds == 0
    assert over.ratio == 1.0  # a meter must not render past full


def test_a_zero_allowance_is_exhausted_rather_than_dividing_by_zero():
    assert VoiceAllowance(used_seconds=0, allowed_seconds=0).exhausted is True
    assert VoiceAllowance(used_seconds=0, allowed_seconds=0).ratio == 1.0


def test_the_notice_says_what_still_works():
    """"Voice is off" reads like the rep is broken. The customer needs to know
    they will still get an answer."""
    assert "keep answering by text" in VOICE_QUOTA_NOTICE
    assert "paused" in VOICE_QUOTA_NOTICE
    assert "renews" in VOICE_QUOTA_NOTICE


# --- the period ----------------------------------------------------------------- #
@pytest.mark.parametrize(
    "when,expected",
    [
        (dt.datetime(2026, 9, 7, 23, 59, tzinfo=dt.UTC), dt.date(2026, 9, 1)),
        (dt.datetime(2026, 9, 1, 0, 0, tzinfo=dt.UTC), dt.date(2026, 9, 1)),
        (dt.datetime(2026, 1, 31, 12, 0, tzinfo=dt.UTC), dt.date(2026, 1, 1)),
        (dt.datetime(2028, 2, 29, 12, 0, tzinfo=dt.UTC), dt.date(2028, 2, 1)),  # leap day
    ],
)
def test_the_period_is_the_calendar_month(when, expected):
    """Matches how monthly_message_quota is already spoken about. A second
    notion of "this month" invented here would put the two meters on different
    clocks, on the same page."""
    assert period_start(when) == expected


def test_usage_resets_when_the_month_does():
    """The allowance is per period, so the same seconds in a new month are a
    fresh start rather than a permanent ban."""
    assert period_start(dt.datetime(2026, 9, 30, tzinfo=dt.UTC)) != period_start(
        dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    )
