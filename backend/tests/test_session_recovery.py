"""Auto-recovery decisions for dead WhatsApp sessions (DESIGN.md §12.1).

The decision is a pure function so the policy can be tested without a database,
WAHA, or a clock, mirroring how app/agent/reminders.py separates predicates
from IO.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.enums import SessionStatus
from app.waha.session_recovery import (
    MAX_RECOVERY_ATTEMPTS,
    RETRY_INTERVAL,
    RecoveryDecision,
    decide_recovery,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _decide(**overrides) -> RecoveryDecision:
    base = {
        "status": SessionStatus.failed,
        "has_credentials": True,
        "attempts": 0,
        "last_attempt_at": None,
        "reachable": True,
        "now": NOW,
    }
    base.update(overrides)
    return decide_recovery(**base)


# --- nothing to do ---------------------------------------------------------- #
def test_working_session_is_left_alone():
    assert _decide(status=SessionStatus.working) is RecoveryDecision.healthy


def test_starting_session_is_left_alone():
    """A session already reconnecting must not be restarted out from under
    itself; that is how a recovering session gets knocked back to FAILED."""
    assert _decide(status=SessionStatus.starting) is RecoveryDecision.healthy


def test_scan_qr_code_is_not_a_failure_to_recover_from():
    assert _decide(status=SessionStatus.scan_qr_code) is RecoveryDecision.healthy


# --- preconditions ---------------------------------------------------------- #
def test_session_without_credentials_needs_a_human():
    """No stored credentials means WhatsApp never authorised this session.
    Restarting only loops it through SCAN_QR_CODE and back to FAILED."""
    assert _decide(has_credentials=False) is RecoveryDecision.needs_qr


def test_no_attempt_while_whatsapp_is_unreachable():
    """The 15 Aug outage killed every session because the container lost
    outbound network. Retrying then is guaranteed to fail, and burning the
    budget on doomed attempts is why a small budget would otherwise not be
    enough."""
    assert _decide(reachable=False) is RecoveryDecision.unreachable


def test_unreachable_is_checked_before_the_attempt_budget():
    """A network outage must not consume the budget even once it is nearly
    spent, or a long outage exhausts recovery before it can ever work."""
    assert (
        _decide(reachable=False, attempts=MAX_RECOVERY_ATTEMPTS)
        is RecoveryDecision.unreachable
    )


# --- the bounded retry ------------------------------------------------------ #
def test_first_failure_restarts_immediately():
    assert _decide() is RecoveryDecision.restart


def test_waits_between_attempts():
    assert (
        _decide(attempts=1, last_attempt_at=NOW - timedelta(minutes=2))
        is RecoveryDecision.wait
    )


def test_retries_once_the_interval_has_passed():
    assert (
        _decide(attempts=1, last_attempt_at=NOW - RETRY_INTERVAL)
        is RecoveryDecision.restart
    )


def test_gives_up_after_the_budget_is_spent():
    assert (
        _decide(
            attempts=MAX_RECOVERY_ATTEMPTS,
            last_attempt_at=NOW - timedelta(hours=2),
        )
        is RecoveryDecision.exhausted
    )


def test_budget_is_fixed_not_exponential():
    """Deliberately bounded: three attempts ten minutes apart covers a short
    outage without ever hammering WhatsApp, which is a ban vector."""
    assert MAX_RECOVERY_ATTEMPTS == 3
    assert timedelta(minutes=10) == RETRY_INTERVAL
