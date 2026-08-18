"""Session-health polling and auto-recovery (DESIGN.md §12.1).

Polls every WAHA session's status, tries to bring failed ones back within a
bounded budget, and records a ``notifications`` row when recovery gives up, so
the dashboard surfaces disconnects (WhatsApp can't carry its own down-alert).

The recovery policy itself lives in :mod:`app.waha.session_recovery` as a pure
function; this module is the IO around it.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.logging import logger
from app.core.tenancy import system_session
from app.models.enums import NotificationType, SessionStatus
from app.models.ops import Notification
from app.models.whatsapp import WhatsAppSession
from app.waha.client import WahaClient, WahaError
from app.waha.session_recovery import (
    MAX_RECOVERY_ATTEMPTS,
    RecoveryDecision,
    decide_recovery,
)

#: Host used to decide whether WhatsApp is reachable at all. This is the same
#: endpoint the NOWEB engine dials, so if it resolves and accepts a connection,
#: a restart has a real chance of succeeding.
_REACHABILITY_HOST = "web.whatsapp.com"
_REACHABILITY_PORT = 443
_REACHABILITY_TIMEOUT = 5.0


async def whatsapp_reachable(
    host: str = _REACHABILITY_HOST, port: int = _REACHABILITY_PORT
) -> bool:
    """Can we resolve and reach WhatsApp right now?

    This gate is the reason the retry budget can stay small. On 15 Aug 2026 the
    container lost DNS and routing for under a minute; every reconnect during
    that window was doomed, and without this check they would have burned the
    entire budget before the network came back.
    """
    try:
        fut = asyncio.open_connection(host, port)
        _reader, writer = await asyncio.wait_for(fut, timeout=_REACHABILITY_TIMEOUT)
    except (OSError, socket.gaierror, TimeoutError):
        return False
    writer.close()
    # Close-time races tell us nothing: the connection already succeeded, which
    # is the only thing this function is asking.
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def poll_session_health(waha: WahaClient) -> int:
    """Check all sessions, attempt bounded recovery, and notify on give-up.

    Returns the number of sessions that exhausted recovery this tick, which is
    what the scheduler logs.
    """
    gave_up = 0
    now = datetime.now(UTC)

    # Probed once per tick rather than per session: it is the same answer for
    # every session and a needless round trip each time otherwise.
    reachable: bool | None = None

    async with system_session() as db:
        sessions = (await db.execute(select(WhatsAppSession))).scalars().all()
        for sess in sessions:
            info: dict = {}
            try:
                info = await waha.get_session(sess.session_name)
                raw_status = str(info.get("status", "")).upper()
            except WahaError as exc:
                logger.bind(session=sess.session_name).warning(
                    f"session status poll failed: {exc}"
                )
                raw_status = SessionStatus.failed.value

            try:
                new_status = SessionStatus(raw_status)
            except ValueError:
                logger.bind(session=sess.session_name).warning(
                    f"unknown WAHA status {raw_status!r}"
                )
                continue

            sess.status = new_status

            # A session that came back is a clean slate. Without this reset a
            # single bad night permanently consumes the budget, and the next
            # unrelated outage gets no recovery at all.
            if new_status is SessionStatus.working:
                if sess.recovery_attempts:
                    logger.bind(session=sess.session_name).info(
                        "session recovered; recovery budget reset"
                    )
                sess.recovery_attempts = 0
                sess.last_recovery_at = None
                continue

            if new_status is not SessionStatus.failed:
                continue

            if reachable is None:
                reachable = await whatsapp_reachable()

            decision = decide_recovery(
                status=new_status,
                # WAHA only populates `me` once WhatsApp has authorised the
                # session. Empty means it was never linked, so there is nothing
                # to restart back into.
                has_credentials=bool(info.get("me")),
                attempts=sess.recovery_attempts,
                last_attempt_at=sess.last_recovery_at,
                reachable=reachable,
                now=now,
            )
            log = logger.bind(
                session=sess.session_name,
                tenant_id=str(sess.tenant_id),
                attempts=sess.recovery_attempts,
            )

            if decision is RecoveryDecision.restart:
                try:
                    await waha.restart_session(sess.session_name)
                except WahaError as exc:
                    log.warning(f"session restart failed: {exc}")
                # Counted whether or not the call succeeded. A restart that
                # errors is still an attempt, and not counting it would loop
                # forever on a permanently broken session.
                sess.recovery_attempts += 1
                sess.last_recovery_at = now
                log.info("session FAILED; restart attempted")

            elif decision is RecoveryDecision.exhausted:
                # Notify once, on the tick that exhausts the budget, not every
                # minute thereafter. One past the cap is the "already told
                # them" marker, which avoids a second column purely to hold a
                # boolean and cannot be confused with the reset on recovery.
                if sess.recovery_attempts == MAX_RECOVERY_ATTEMPTS:
                    gave_up += 1
                    db.add(
                        Notification(
                            tenant_id=sess.tenant_id,
                            type=NotificationType.session_failed,
                            title="WhatsApp session disconnected",
                            body=(
                                f"Session '{sess.label or sess.session_name}' is "
                                "down and could not be reconnected automatically. "
                                "Reconnect it from the dashboard."
                            ),
                            meta={"session_name": sess.session_name},
                        )
                    )
                    sess.recovery_attempts += 1
                    log.error("session FAILED; recovery exhausted, owner notified")

            elif decision is RecoveryDecision.needs_qr:
                log.info("session FAILED with no credentials; needs a QR scan")

            elif decision is RecoveryDecision.unreachable:
                log.warning("session FAILED but WhatsApp unreachable; not retrying")

    return gave_up


__all__ = ["poll_session_health", "whatsapp_reachable"]
