"""Telling the owner their number stopped replying (functional test F4).

A real tenant's WhatsApp session sat at FAILED for days. Fleet Health reported
it accurately and nothing else did: no notification, no email, no badge. The
only alert in the codebase hung off the *recovery budget* -- it fires on
``RecoveryDecision.exhausted``, after three restart attempts -- and the session
that was actually down had no stored credentials, so its decision was
``needs_qr``: nothing retried, nothing exhausted, nobody told, indefinitely.

These tests pin the two properties that make an alert trustworthy:

* it happens at all, once, when a session leaves WORKING;
* it does not happen again while the session stays down.

The second is the one that gets warning systems switched off. The poller runs
every 60 seconds, so a dedupe on the state persisting rather than on the
transition into it would be 1,440 notifications a day per dead number.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from app.models.enums import SessionStatus
from app.services import notifications as notif
from app.services.notifications import (
    SESSION_BACK_TITLE,
    SESSION_DOWN_GRACE,
    SESSION_DOWN_TITLE,
    FleetSession,
    SessionAlertDecision,
    decide_session_alert,
    sweep_session_alerts,
)

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.UTC)
TENANT = uuid.uuid4()


def _session(status: SessionStatus = SessionStatus.failed) -> FleetSession:
    return FleetSession(
        tenant_id=TENANT,
        session_name="test01-b9a90901",
        label="test01",
        status=status,
    )


@pytest.fixture
def sent(monkeypatch) -> list[tuple[str, str]]:
    """Capture what the owner would have been told, delivering nothing.

    The delivery path is stubbed at ``_tell_owner`` rather than at the email
    transport: the point of these tests is the decision to speak, and stubbing
    lower would drag a database and an SMTP config into a policy test.
    """
    calls: list[tuple[str, str]] = []

    async def fake_tell(sess, *, title, body, send_gateway):  # noqa: ANN001
        calls.append((title, body))
        return True

    monkeypatch.setattr(notif, "_tell_owner", fake_tell)
    return calls


# --- the decision, without IO ------------------------------------------------ #
def _decide(**overrides) -> SessionAlertDecision:
    base = {
        "status": SessionStatus.failed,
        "down_since": NOW - SESSION_DOWN_GRACE,
        "already_alerted": False,
        "now": NOW,
    }
    return decide_session_alert(**{**base, **overrides})


def test_a_failed_session_past_the_grace_period_is_worth_telling_someone():
    assert _decide() is SessionAlertDecision.alert


def test_a_working_session_closes_the_episode():
    assert _decide(status=SessionStatus.working) is SessionAlertDecision.healthy


def test_starting_is_not_an_outage():
    """Every restart of the stack takes each session through STARTING. Treating
    that as down means a page for every tenant on every deploy."""
    assert _decide(status=SessionStatus.starting) is SessionAlertDecision.in_flight


@pytest.mark.parametrize(
    "status",
    [SessionStatus.failed, SessionStatus.stopped, SessionStatus.scan_qr_code],
)
def test_every_state_where_the_rep_is_silent_alerts(status):
    """Auto-recovery only ever notified on exhausted FAILED. A logged-out number
    (SCAN_QR_CODE) and a stopped one are just as silent to the customer."""
    assert _decide(status=status) is SessionAlertDecision.alert


def test_a_brief_blip_waits():
    assert _decide(down_since=NOW - dt.timedelta(seconds=30)) is SessionAlertDecision.wait


def test_the_first_sighting_waits_rather_than_firing_blind():
    assert _decide(down_since=None) is SessionAlertDecision.wait


def test_staying_down_is_silent_not_repeated():
    assert _decide(already_alerted=True) is SessionAlertDecision.silent


# --- the sweep, against a real Redis ----------------------------------------- #
async def test_one_alert_when_a_session_leaves_working(fake_redis, sent):
    """The F4 regression, end to end over the marker store.

    WORKING, then FAILED, then FAILED for the rest of the day: exactly one
    notification, raised once the outage has outlived the grace period.
    """
    working = [_session(SessionStatus.working)]
    failed = [_session(SessionStatus.failed)]

    await sweep_session_alerts(fake_redis, now=NOW, sessions=working)
    assert sent == []

    # The transition itself. Nothing yet: a single bad tick is a blip.
    await sweep_session_alerts(fake_redis, now=NOW, sessions=failed)
    assert sent == []

    # Still down four minutes later, which is an outage.
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=4), sessions=failed
    )
    assert [title for title, _ in sent] == [SESSION_DOWN_TITLE]

    # And then all day. This is the assertion that keeps the feature switched on.
    for minute in (5, 6, 20, 60, 600):
        await sweep_session_alerts(
            fake_redis, now=NOW + dt.timedelta(minutes=minute), sessions=failed
        )
    assert [title for title, _ in sent] == [SESSION_DOWN_TITLE]


async def test_the_alert_names_the_session_and_what_to_do(fake_redis, sent):
    await sweep_session_alerts(fake_redis, now=NOW, sessions=[_session()])
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=4), sessions=[_session()]
    )

    _title, body = sent[0]
    assert "test01" in body
    assert "Connect" in body


async def test_recovery_is_reported_and_re_arms_the_alarm(fake_redis, sent):
    """An owner told the number was down and never told it came back has to
    guess. And the next outage is a new outage: it alerts again."""
    failed, working = [_session()], [_session(SessionStatus.working)]

    await sweep_session_alerts(fake_redis, now=NOW, sessions=failed)
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=4), sessions=failed
    )
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=5), sessions=working
    )
    assert [title for title, _ in sent] == [SESSION_DOWN_TITLE, SESSION_BACK_TITLE]

    later = NOW + dt.timedelta(hours=3)
    await sweep_session_alerts(fake_redis, now=later, sessions=failed)
    await sweep_session_alerts(
        fake_redis, now=later + dt.timedelta(minutes=4), sessions=failed
    )
    assert [title for title, _ in sent] == [
        SESSION_DOWN_TITLE,
        SESSION_BACK_TITLE,
        SESSION_DOWN_TITLE,
    ]


async def test_a_restart_attempt_does_not_reset_the_episode(fake_redis, sent):
    """FAILED -> STARTING -> FAILED is one outage. If STARTING cleared the
    markers, every recovery attempt would produce a fresh alert."""
    failed = [_session()]
    starting = [_session(SessionStatus.starting)]

    await sweep_session_alerts(fake_redis, now=NOW, sessions=failed)
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=4), sessions=failed
    )
    assert len(sent) == 1

    for minute in (5, 6, 7):
        await sweep_session_alerts(
            fake_redis, now=NOW + dt.timedelta(minutes=minute), sessions=starting
        )
        await sweep_session_alerts(
            fake_redis, now=NOW + dt.timedelta(minutes=minute, seconds=30), sessions=failed
        )
    assert len(sent) == 1


async def test_a_delivery_failure_is_retried_rather_than_remembered(
    fake_redis, monkeypatch
):
    """The marker is set on a written notification, not on an attempt. A
    database blip that swallowed the only alert would be the same class of bug
    this whole finding is about."""
    outcomes = [False, True]
    calls: list[str] = []

    async def flaky(sess, *, title, body, send_gateway):  # noqa: ANN001
        calls.append(title)
        return outcomes.pop(0)

    monkeypatch.setattr(notif, "_tell_owner", flaky)

    failed = [_session()]
    await sweep_session_alerts(fake_redis, now=NOW, sessions=failed)
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=4), sessions=failed
    )
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=5), sessions=failed
    )
    assert calls == [SESSION_DOWN_TITLE, SESSION_DOWN_TITLE]

    # And once it lands, it stops.
    await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=6), sessions=failed
    )
    assert len(calls) == 2


async def test_one_tenants_outage_does_not_silence_the_fleet(fake_redis, sent):
    others = [
        FleetSession(uuid.uuid4(), "a-1", "A", SessionStatus.failed),
        FleetSession(uuid.uuid4(), "b-2", "B", SessionStatus.scan_qr_code),
        FleetSession(uuid.uuid4(), "c-3", "C", SessionStatus.working),
    ]
    await sweep_session_alerts(fake_redis, now=NOW, sessions=others)
    stats = await sweep_session_alerts(
        fake_redis, now=NOW + dt.timedelta(minutes=4), sessions=others
    )
    assert stats["alerted"] == 2
    assert len(sent) == 2


# --------------------------------------------------------------------------- #
# The two messages about one outage must not be the same message twice
# --------------------------------------------------------------------------- #
#
# There are two senders, and reconciling them was left open until the timings
# were laid out. sweep_session_alerts speaks at T+3min (SESSION_DOWN_GRACE);
# poll_session_health speaks on RecoveryDecision.exhausted, which is three
# restarts at RETRY_INTERVAL apart, so T+30min. That is an escalation and worth
# keeping -- the second one is the one that means "this will not fix itself".
#
# It only reads as an escalation if the first message does not already claim
# the thing the second one exists to say. It did: at T+3min, with restarts
# still scheduled for T+10 and T+20, the body said "could not be restored on
# its own".


def test_the_first_alert_does_not_claim_recovery_failed_while_it_is_running():
    """Sent three minutes in, with two restarts still to come."""
    sess = FleetSession(
        tenant_id=TENANT,
        session_name="test01-b9a90901",
        label="test01",
        status=SessionStatus.failed,
        phone_number="+923001234567",
        recovery_attempts=0,
    )
    assert sess.recovery_in_progress

    body = notif._down_body(sess)
    assert "could not be restored" not in body
    # And it says why there may be nothing to do, so the owner is not sent to
    # the dashboard for something that is about to fix itself.
    assert "reconnecting it automatically" in body


def test_the_first_alert_does_say_so_when_nothing_will_retry():
    """No stored credentials means decide_recovery returns needs_qr: nothing
    restarts, nothing exhausts, and no second message is ever coming. Promising
    one would be the F4 failure with better wording."""
    sess = FleetSession(
        tenant_id=TENANT,
        session_name="test01-b9a90901",
        label="test01",
        status=SessionStatus.failed,
        phone_number=None,
    )
    assert not sess.recovery_in_progress

    body = notif._down_body(sess)
    assert "could not be restored on its own" in body
    assert "reconnecting it automatically" not in body


def test_recovery_in_progress_is_false_once_the_budget_is_spent():
    from app.waha.session_recovery import MAX_RECOVERY_ATTEMPTS

    sess = FleetSession(
        tenant_id=TENANT,
        session_name="test01-b9a90901",
        label="test01",
        status=SessionStatus.failed,
        phone_number="+923001234567",
        recovery_attempts=MAX_RECOVERY_ATTEMPTS,
    )
    assert not sess.recovery_in_progress


def test_the_escalation_notice_is_distinguishable_from_the_first_alert():
    """Both rows are NotificationType.session_failed, so the copy and the meta
    are the only things telling an owner -- or the dashboard -- that the second
    row is news rather than a repeat."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "waha" / "session_health.py"
    ).read_text()
    exhausted = next(
        ast.unparse(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and "RecoveryDecision.exhausted" in ast.unparse(node)
    )

    assert "recovery_exhausted" in exhausted, "the row must be machine-distinguishable"
    assert SESSION_DOWN_TITLE not in exhausted, (
        "the escalation reuses the first alert's title, so it reads as a duplicate"
    )
