"""Owner alerts + the dashboard notification log (DESIGN.md §5.5, §12.1).

Three things live here:

* :func:`notify` — write a ``notifications`` row and, when configured, alert the
  owner on their own WhatsApp number through the single send gateway (never the
  raw WAHA client — §5.6).
* :func:`sweep_session_alerts` — tell the owner their number stopped replying.
  Called from the scheduler, one alert per outage episode.
* :func:`supersede_stale_notices` — mark a notice whose basis was later
  corrected as no longer applying, without rewriting history.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.tenancy import system_session, tenant_session
from app.models.enums import NotificationType, SessionStatus
from app.models.ops import Notification
from app.models.tenant import TenantConfig
from app.models.whatsapp import WhatsAppSession
from app.waha.send_gateway import SendGateway


async def notify(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    body: str | None = None,
    type: NotificationType = NotificationType.escalation,  # noqa: A002 - matches API/enum naming
    meta: dict | None = None,
    send_gateway: SendGateway | None = None,
) -> Notification:
    """Log a dashboard notification and, when configured, alert the owner on WhatsApp.

    Always writes a ``notifications`` row. When the tenant has an
    ``owner_alert_number`` configured, a working WhatsApp session, and a
    ``send_gateway`` was supplied, also sends a WhatsApp message to that number.
    A missing gateway/config/session is not an error — the dashboard log is the
    guaranteed side effect; the WhatsApp alert is best-effort.
    """
    note = Notification(tenant_id=tenant_id, type=type, title=title, body=body, meta=meta or {})
    db.add(note)
    await db.flush()

    if send_gateway is None:
        return note

    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if config is None or not config.owner_alert_number:
        return note

    session_row = (
        await db.execute(
            select(WhatsAppSession).where(
                WhatsAppSession.tenant_id == tenant_id,
                WhatsAppSession.status == SessionStatus.working,
            )
        )
    ).scalars().first()
    if session_row is None:
        return note

    text = f"{title}\n{body}" if body else title
    try:
        await send_gateway.send_text(session_row.session_name, config.owner_alert_number, text)
    except Exception as exc:  # noqa: BLE001 — alert delivery must never break the caller's flow
        logger.bind(tenant_id=str(tenant_id)).warning(f"owner alert send failed: {exc}")
    return note


# --------------------------------------------------------------------------- #
# "Your number stopped replying" (functional test F4)
# --------------------------------------------------------------------------- #
# A tenant's session sat at FAILED for days and nobody was told. Fleet Health
# reported it accurately and nothing else did: no notification, no email, no
# badge. The only alert that existed lived in ``poll_session_health`` and fires
# on one branch only — ``RecoveryDecision.exhausted``, i.e. after three restart
# attempts. The session that was actually down never reached it: with no stored
# credentials the decision is ``needs_qr``, which retries nothing, exhausts
# nothing, and therefore notified nobody, forever.
#
# So the alert cannot hang off the recovery budget. It hangs off the status the
# poller has already written, which covers every way a number can stop
# answering, including the ways auto-recovery deliberately does not touch.

#: The rep is not answering in any of these. STARTING is excluded on purpose:
#: it is the state a restart passes through, and treating it as an outage means
#: an alert every time WAHA or the stack is redeployed.
DOWN_STATUSES = frozenset(
    {SessionStatus.failed, SessionStatus.stopped, SessionStatus.scan_qr_code}
)

SESSION_DOWN_TITLE = "Your WhatsApp number stopped replying"
SESSION_BACK_TITLE = "Your WhatsApp number is back online"

#: How long a session must look down before the owner is told. The poller runs
#: every 60s, so this is "a few ticks", not "a few minutes of guessing": it
#: exists so a stack restart, which stops and starts every session, does not
#: page three tenants on the way past. Small enough to still satisfy F4's
#: "within minutes".
SESSION_DOWN_GRACE = dt.timedelta(minutes=3)

#: Redis keys. Two per session: when it was first seen down (the episode) and
#: whether the owner has already been told about that episode.
_DOWN_SINCE_KEY = "qonvo:session_down_since:{name}"
_ALERTED_KEY = "qonvo:session_alerted:{name}"

#: Long enough that a week-long outage is still one alert, short enough that a
#: deleted session does not leave keys behind for ever.
_MARKER_TTL = int(dt.timedelta(days=14).total_seconds())


class SessionAlertDecision(enum.StrEnum):
    """What to do about one session this tick. Pure; see :func:`decide_session_alert`."""

    healthy = "healthy"
    """Working. Clear the episode, and say so if we had raised an alarm."""

    in_flight = "in_flight"
    """STARTING. Mid-reconnect: neither an outage nor a recovery yet."""

    wait = "wait"
    """Down, but not for long enough to be worth an owner's attention."""

    alert = "alert"
    """Down past the grace period, and the owner has not been told."""

    silent = "silent"
    """Down, and already alerted. This is the anti-spam branch."""


def decide_session_alert(
    *,
    status: SessionStatus,
    down_since: dt.datetime | None,
    already_alerted: bool,
    now: dt.datetime,
    grace: dt.timedelta = SESSION_DOWN_GRACE,
) -> SessionAlertDecision:
    """Decide, without IO, whether this session's owner should hear from us.

    The dedupe is on the *transition* into a bad state, not on the state
    persisting: ``already_alerted`` is cleared only by a WORKING observation,
    so a session that stays down is silent for ever after the first alert, and
    one that flaps WORKING → FAILED → WORKING → FAILED is alerted once per
    genuine outage rather than once per tick.
    """
    if status is SessionStatus.working:
        return SessionAlertDecision.healthy
    if status not in DOWN_STATUSES:
        # STARTING, or a status WAHA grows later that we do not understand yet.
        # Silence is the safe default for both: an unknown state is not
        # evidence of an outage.
        return SessionAlertDecision.in_flight
    if already_alerted:
        return SessionAlertDecision.silent
    if down_since is None or now - down_since < grace:
        return SessionAlertDecision.wait
    return SessionAlertDecision.alert


@dataclass(frozen=True, slots=True)
class FleetSession:
    """One session's identity and last-known status, read across tenants."""

    tenant_id: uuid.UUID
    session_name: str
    label: str | None
    status: SessionStatus
    #: Set once the number has been linked, so it doubles as "there are
    #: credentials to restart back into" -- which is what decides whether
    #: auto-recovery will even be attempted (session_recovery.decide_recovery
    #: returns needs_qr without them).
    phone_number: str | None = None
    #: How many restarts have been spent. Read only to keep the copy honest:
    #: at the cap, auto-recovery has given up and the owner has to act.
    recovery_attempts: int = 0

    @property
    def display(self) -> str:
        return self.label or self.session_name

    @property
    def recovery_in_progress(self) -> bool:
        """Is something still going to try to fix this without the owner?

        The first alert goes out three minutes into an outage, and restarts run
        at T+0/T+10/T+20 -- so at the time we write to the owner, recovery is
        usually still going. The body used to say "could not be restored on its
        own" anyway, which was both untrue and indistinguishable from the
        genuine give-up notice that arrives at T+30.
        """
        from app.waha.session_recovery import MAX_RECOVERY_ATTEMPTS

        return (
            self.status is SessionStatus.failed
            and bool(self.phone_number)
            and self.recovery_attempts < MAX_RECOVERY_ATTEMPTS
        )


async def fleet_sessions() -> list[FleetSession]:
    """Every session on the box, with the status the health poll last wrote.

    ``system_session`` (BYPASSRLS) because this is a cross-tenant fleet scan,
    the same reason ``poll_session_health`` uses it. Read only, and detached
    into plain values so the alerting below runs outside this transaction.
    """
    async with system_session() as db:
        rows = (await db.execute(select(WhatsAppSession))).scalars().all()
        return [
            FleetSession(
                tenant_id=row.tenant_id,
                session_name=row.session_name,
                label=row.label,
                status=row.status,
                phone_number=row.phone_number,
                recovery_attempts=row.recovery_attempts,
            )
            for row in rows
        ]


async def _tell_owner(
    sess: FleetSession,
    *,
    title: str,
    body: str,
    send_gateway: SendGateway | None,
) -> bool:
    """Notification row + email, in the tenant's own transaction.

    Best effort: an alert that cannot be delivered must not abort the sweep and
    leave the rest of the fleet unwatched. Returns True when the notification
    row was written, which is what the Redis marker is set on — an email that
    bounces must not cost the owner the dashboard row, and a failed write must
    not be remembered as "already told them".
    """
    from app.services.email import email_owner

    try:
        async with tenant_session(sess.tenant_id) as db:
            await notify(
                db,
                tenant_id=sess.tenant_id,
                type=NotificationType.session_failed,
                title=title,
                body=body,
                meta={"session_name": sess.session_name, "status": sess.status.value},
                # Sent through the gateway so a tenant with a second, working
                # number still gets the WhatsApp ping. notify() finds a WORKING
                # session or quietly skips, which is the usual case here: the
                # number we are alerting about is the one that is down.
                send_gateway=send_gateway,
            )
            await email_owner(db, sess.tenant_id, title, body)
        return True
    except Exception as exc:  # noqa: BLE001 — one tenant's failure is not the fleet's
        logger.bind(session=sess.session_name, tenant_id=str(sess.tenant_id)).warning(
            f"session alert delivery failed: {exc}"
        )
        return False


def _down_body(sess: FleetSession) -> str:
    if sess.status is SessionStatus.scan_qr_code:
        detail = (
            "WhatsApp has logged the number out, so it needs to be linked again "
            "by scanning a QR code."
        )
    elif sess.status is SessionStatus.stopped:
        detail = "The connection is stopped."
    elif sess.recovery_in_progress:
        # True at the time this is sent, which "could not be restored" was not.
        return (
            f"Your rep is not answering on '{sess.display}'. The connection "
            "dropped and customers messaging you right now are getting no "
            "reply. We are reconnecting it automatically and will write again "
            "if that does not work, so there may be nothing for you to do. "
            "To reconnect it yourself, open Connect in your dashboard."
        )
    else:
        detail = "The connection dropped and could not be restored on its own."
    return (
        f"Your rep is not answering on '{sess.display}'. {detail} "
        "Customers messaging you right now are getting no reply. "
        "Open Connect in your dashboard to link the number again."
    )


async def sweep_session_alerts(
    redis: Any,
    *,
    send_gateway: SendGateway | None = None,
    now: dt.datetime | None = None,
    sessions: list[FleetSession] | None = None,
) -> dict[str, int]:
    """Alert owners whose number has stopped replying. One alert per episode.

    Episode state lives in Redis rather than on the session row because the
    alternative was a migration, and because the two facts being stored are
    genuinely transient: when this outage started, and whether we have spoken
    about it. Losing them (a flushed Redis) costs at most one repeat alert,
    which is the right way round for a warning system.

    ``sessions`` is injectable so the decision-and-delivery path can be tested
    without a database.
    """
    now = now or dt.datetime.now(dt.UTC)
    fleet = sessions if sessions is not None else await fleet_sessions()
    stats = {"alerted": 0, "recovered": 0, "down": 0}

    for sess in fleet:
        down_key = _DOWN_SINCE_KEY.format(name=sess.session_name)
        alerted_key = _ALERTED_KEY.format(name=sess.session_name)

        raw_since = await redis.get(down_key)
        down_since = _parse_ts(raw_since)
        already_alerted = bool(await redis.get(alerted_key))

        decision = decide_session_alert(
            status=sess.status,
            down_since=down_since,
            already_alerted=already_alerted,
            now=now,
        )
        log = logger.bind(
            session=sess.session_name,
            tenant_id=str(sess.tenant_id),
            status=sess.status.value,
        )

        if decision is SessionAlertDecision.healthy:
            # Closing the loop matters as much as opening it: an owner who was
            # told the number was down and never told it came back has to guess.
            if already_alerted:
                await _tell_owner(
                    sess,
                    title=SESSION_BACK_TITLE,
                    body=(
                        f"'{sess.display}' is connected again and your rep is "
                        "answering customers. Nothing else needs doing."
                    ),
                    send_gateway=send_gateway,
                )
                stats["recovered"] += 1
                log.info("session recovered; owner told")
            await redis.delete(down_key, alerted_key)
            continue

        if decision is SessionAlertDecision.in_flight:
            # Deliberately leaves both markers alone. A FAILED → STARTING →
            # FAILED loop is one outage, and clearing the episode here would
            # re-alert on every restart attempt.
            continue

        stats["down"] += 1

        if down_since is None:
            await redis.set(down_key, now.isoformat(), ex=_MARKER_TTL)

        if decision is not SessionAlertDecision.alert:
            continue

        if await _tell_owner(
            sess,
            title=SESSION_DOWN_TITLE,
            body=_down_body(sess),
            send_gateway=send_gateway,
        ):
            # Set only after the row exists, so a database blip retries next
            # tick instead of silently swallowing the only alert.
            await redis.set(alerted_key, now.isoformat(), ex=_MARKER_TTL)
            stats["alerted"] += 1
            log.error("session down past grace; owner notified")

    return stats


def _parse_ts(raw: str | bytes | None) -> dt.datetime | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


# --------------------------------------------------------------------------- #
# Notices whose basis was later corrected (functional test F6)
# --------------------------------------------------------------------------- #
# Two "Voice replies are paused" rows are sitting in production. They were sent
# an hour apart by a dedupe that tested a marker nothing ever wrote (fixed), and
# then the meter they were computed from was corrected *downward*: it reads 2 of
# 5 minutes, so voice was never exhausted and voice replies never stopped.
#
# Three options were on the table: delete the rows, supersede them, or flag them
# stale. This supersedes, and derives it rather than storing it:
#
# * Deleting is the only one that loses information. The owner received those
#   notices; one of them may be why they have not sent a voice note since. A
#   product that silently un-sends what it said is harder to trust than one that
#   admits it was wrong, and support cannot reconstruct a conversation about a
#   row that no longer exists.
# * Storing a ``stale`` flag needs a writer, and a writer is the thing that was
#   missing in the first place. A flag set by a job that stops running is a
#   third way to be quietly wrong.
# * Deriving it costs one aggregate query, is always current, and self-corrects
#   in both directions: if the allowance genuinely runs out later this period,
#   the same notice stops being superseded, because it is true again.
#
# The row is kept, shown as no longer applying, and left out of the unread count
# so it stops demanding attention it does not deserve.


async def stale_reasons(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    rows: list[Notification],
    *,
    now: dt.datetime | None = None,
) -> dict[uuid.UUID, str]:
    """Which of these notifications no longer hold, and in what words.

    Keyed by notification id, so the API can attach a plain-English retraction
    to the row rather than the reader having to work out that a notice from
    yesterday was overtaken by a correction today.

    Only the current period is reconciled. A notice from a closed month was
    true when it was sent, against a meter that has since reset; re-judging it
    against this month's numbers would be a new kind of wrong.
    """
    from app.agent.voice_allowance import (
        VOICE_QUOTA_NOTIFICATION_TITLE,
        voice_allowance,
    )

    now = now or dt.datetime.now(dt.UTC)
    boundary = _period_boundary(now)

    # Filtered in Python off rows the caller already loaded: the common case is
    # a tenant with no such notice at all, and that case must cost nothing.
    candidates = [
        row
        for row in rows
        if row.title == VOICE_QUOTA_NOTIFICATION_TITLE
        and _aware(row.created_at) >= boundary
    ]
    if not candidates:
        return {}

    allowance = await voice_allowance(db, tenant_id, now=now)
    if allowance.exhausted:
        return {}

    reason = (
        "No longer applies. Voice was re-measured after this was sent: your rep "
        f"has used {allowance.used_minutes} of {allowance.allowed_minutes} voice "
        f"minutes this month ({allowance.used_seconds} of "
        f"{allowance.allowed_seconds} seconds), so voice replies were never "
        "paused and have kept working."
    )
    return {row.id: reason for row in candidates}


def _period_boundary(now: dt.datetime) -> dt.datetime:
    from app.agent.voice_allowance import period_start_dt

    return period_start_dt(now)


def _aware(value: dt.datetime) -> dt.datetime:
    """``created_at`` is timestamptz in Postgres and naive in a fake session."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


__all__ = [
    "DOWN_STATUSES",
    "SESSION_BACK_TITLE",
    "SESSION_DOWN_GRACE",
    "SESSION_DOWN_TITLE",
    "FleetSession",
    "SessionAlertDecision",
    "decide_session_alert",
    "fleet_sessions",
    "notify",
    "stale_reasons",
    "sweep_session_alerts",
]
