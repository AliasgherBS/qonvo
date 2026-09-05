"""New-number warm-up schedule (DESIGN.md §5.6).

The spec is week 1 at 50/day, week 2 at 150/day, then normal. The caps were
implemented (``effective_daily_cap``) and the column existed, but nothing ever
set or advanced ``warmup_stage`` -- every session sat at 0, so no number was
ever actually warmed up.

The decision is a pure function, mirroring app/waha/session_recovery.py, so the
policy can be tested without a database or a clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.sessions import CreateSessionRequest
from app.models.whatsapp import WhatsAppSession
from app.waha.session_warmup import next_warmup_stage

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _next(stage: int, age_days: float) -> int | None:
    return next_warmup_stage(stage, NOW - timedelta(days=age_days), now=NOW)


# --- staying put ------------------------------------------------------------ #
def test_first_week_stays_in_stage_one():
    assert _next(1, 3) is None


def test_second_week_stays_in_stage_two():
    assert _next(2, 10) is None


def test_a_normal_session_is_never_re_warmed():
    """Stage 0 is terminal. It is also what an operator sets to clear warm-up on
    a number that is already established, so ageing must never undo that."""
    assert _next(0, 1) is None
    assert _next(0, 365) is None


# --- advancing -------------------------------------------------------------- #
def test_stage_one_advances_to_two_after_a_week():
    assert _next(1, 7) == 2


def test_stage_two_clears_after_a_fortnight():
    assert _next(2, 14) == 0


def test_a_long_stale_session_catches_up_in_one_step():
    """A session that missed ticks (worker down, box asleep) must not need one
    tick per week to catch up."""
    assert _next(1, 60) == 0


# --- where the schedule starts ---------------------------------------------- #
def test_a_new_session_starts_warming():
    """A freshly connected number begins at stage 1, not at the normal cap.

    Asserted on the request schema, not the ORM default: the create endpoint
    always passes ``body.warmup_stage`` explicitly, so the model default never
    reaches a real insert.
    """
    assert CreateSessionRequest.model_fields["warmup_stage"].default == 1
    assert WhatsAppSession.__table__.c.warmup_stage.default.arg == 1


def test_an_established_number_can_skip_warm_up():
    """Connecting a number that is already established stays supported."""
    body = CreateSessionRequest(session_name="s1", warmup_stage=0)
    assert body.warmup_stage == 0
