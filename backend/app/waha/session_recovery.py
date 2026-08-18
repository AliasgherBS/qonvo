"""Auto-recovery policy for dead WhatsApp sessions (DESIGN.md §12.1).

Before this existed, ``poll_session_health`` detected a FAILED session and
recorded a notification, but nothing ever tried to bring it back. A session
that died at 2am stayed dead until a human opened the Fleet console and
clicked Restart, which for a "fully managed" product means the owner silently
loses every customer message in the meantime. That is exactly what happened on
15 Aug 2026: the container lost outbound network for under a minute, WAHA
force-stopped every session as "stuck in STARTING", and they sat FAILED for
three days.

The policy is deliberately conservative, and the decision is a pure function so
it can be tested without a database, WAHA or a clock.

Two preconditions gate every attempt:

* **Credentials must exist.** A session WhatsApp never authorised has no
  ``me``; restarting it just loops SCAN_QR_CODE -> FAILED forever. Only a
  person with the phone can fix that, so we leave it for them.
* **WhatsApp must be reachable.** Retrying during a network outage cannot
  possibly work. Checking first is what lets the attempt budget stay small:
  attempts are only spent when they have a real chance, so three of them are
  enough rather than needing an ever-growing backoff to outlast the outage.

The budget is fixed rather than exponential: at most three attempts, ten
minutes apart. Reconnecting in a tight loop is a ban vector, and an
open-ended exponential schedule keeps a hopeless session retrying for hours.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta

from app.models.enums import SessionStatus

#: Attempts per failure episode. Reset as soon as the session is seen WORKING,
#: so unrelated outages weeks apart do not share a budget.
MAX_RECOVERY_ATTEMPTS = 3

#: Fixed gap between attempts. Three attempts covers roughly a 20 minute
#: outage, which is the common case (a laptop sleeping, a flaky link).
RETRY_INTERVAL = timedelta(minutes=10)


class RecoveryDecision(enum.StrEnum):
    """What the poller should do with one session this tick."""

    healthy = "healthy"
    """Not failed. Nothing to do."""

    needs_qr = "needs_qr"
    """Failed with no credentials. Only a human with the phone can fix it."""

    unreachable = "unreachable"
    """Failed, but WhatsApp is unreachable. Do not spend an attempt."""

    restart = "restart"
    """Failed, recoverable, and due. Stop then start the session."""

    wait = "wait"
    """Failed and recoverable, but the retry interval has not elapsed."""

    exhausted = "exhausted"
    """Budget spent. Escalate to the owner once and stop trying."""


def decide_recovery(
    *,
    status: SessionStatus,
    has_credentials: bool,
    attempts: int,
    last_attempt_at: datetime | None,
    reachable: bool,
    now: datetime,
) -> RecoveryDecision:
    """Decide what to do with a single session. Pure; no IO."""
    # STARTING is deliberately treated as healthy. A session already
    # reconnecting must not be restarted out from under itself, or the poller
    # knocks a recovering session back to FAILED every minute.
    if status is not SessionStatus.failed:
        return RecoveryDecision.healthy

    if not has_credentials:
        return RecoveryDecision.needs_qr

    # Checked before the budget on purpose: a long outage must not consume
    # attempts, or recovery is exhausted before it could ever have worked.
    if not reachable:
        return RecoveryDecision.unreachable

    if attempts >= MAX_RECOVERY_ATTEMPTS:
        return RecoveryDecision.exhausted

    if last_attempt_at is not None and now - last_attempt_at < RETRY_INTERVAL:
        return RecoveryDecision.wait

    return RecoveryDecision.restart


__all__ = [
    "MAX_RECOVERY_ATTEMPTS",
    "RETRY_INTERVAL",
    "RecoveryDecision",
    "decide_recovery",
]
