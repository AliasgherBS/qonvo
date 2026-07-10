"""Booking reminder predicates + rendering + opt-out (DESIGN.md §5.7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.agent.reminders import (
    is_stop_message,
    needs_confirmation,
    needs_reminder,
    plan_for_booking,
    render_confirmation,
)
from app.models.enums import BookingStatus

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _booking(**overrides):
    base = {
        "status": BookingStatus.confirmed,
        "conversation_id": uuid.uuid4(),
        "confirmation_sent_at": None,
        "reminder_sent_at": None,
        "scheduled_at": NOW + timedelta(days=2),
        "data": {"summary": "Haircut"},
        "customer_phone": "923001234567",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# --- confirmation ---------------------------------------------------------------- #
def test_needs_confirmation_true_for_fresh_future_booking():
    assert needs_confirmation(_booking(), now=NOW) is True


def test_no_confirmation_once_sent():
    assert needs_confirmation(_booking(confirmation_sent_at=NOW), now=NOW) is False


def test_no_confirmation_without_conversation():
    assert needs_confirmation(_booking(conversation_id=None), now=NOW) is False


def test_no_confirmation_for_cancelled():
    assert needs_confirmation(_booking(status=BookingStatus.cancelled), now=NOW) is False


def test_no_confirmation_for_past_booking():
    assert needs_confirmation(_booking(scheduled_at=NOW - timedelta(hours=1)), now=NOW) is False


# --- 24h reminder ---------------------------------------------------------------- #
def test_needs_reminder_within_window():
    b = _booking(scheduled_at=NOW + timedelta(hours=12))
    assert needs_reminder(b, now=NOW, lookahead_hours=24) is True


def test_no_reminder_outside_window():
    b = _booking(scheduled_at=NOW + timedelta(hours=48))
    assert needs_reminder(b, now=NOW, lookahead_hours=24) is False


def test_no_reminder_once_sent():
    b = _booking(scheduled_at=NOW + timedelta(hours=12), reminder_sent_at=NOW)
    assert needs_reminder(b, now=NOW) is False


# --- plan: confirmation wins, then reminder, then nothing ------------------------- #
def test_plan_prefers_confirmation():
    plan = plan_for_booking(_booking(scheduled_at=NOW + timedelta(hours=12)), now=NOW)
    assert plan is not None and plan.kind == "confirmation"


def test_plan_reminder_when_confirmed_already():
    b = _booking(
        scheduled_at=NOW + timedelta(hours=12), confirmation_sent_at=NOW - timedelta(days=1)
    )
    plan = plan_for_booking(b, now=NOW)
    assert plan is not None and plan.kind == "reminder"


def test_plan_none_when_both_sent():
    b = _booking(confirmation_sent_at=NOW, reminder_sent_at=NOW)
    assert plan_for_booking(b, now=NOW) is None


def test_render_confirmation_includes_summary_and_optout():
    text = render_confirmation(_booking())
    assert "Haircut" in text
    assert "STOP" in text


# --- opt-out detection ----------------------------------------------------------- #
def test_is_stop_message_variants():
    for msg in ["stop", "STOP", "  Stop  ", "unsubscribe", "please unsubscribe me", "rok do"]:
        assert is_stop_message(msg) is True


def test_is_stop_message_ignores_normal_text():
    for msg in ["do you stop at 5pm?", "what time do you close", "", None]:
        assert is_stop_message(msg) is False
