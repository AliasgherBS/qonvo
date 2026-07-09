"""Session-health polling (DESIGN.md §12.1).

Polls every WAHA session's status and records a ``notifications`` row when a
session transitions into ``FAILED``, so the dashboard/ops console surfaces
disconnects (WhatsApp itself can't carry its own down-alert).
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.logging import logger
from app.core.tenancy import system_session
from app.models.enums import NotificationType, SessionStatus
from app.models.ops import Notification
from app.models.whatsapp import WhatsAppSession
from app.waha.client import WahaClient, WahaError


async def poll_session_health(waha: WahaClient) -> int:
    """Check all sessions; persist status changes and FAILED notifications.

    Returns the number of sessions newly marked FAILED.
    """
    newly_failed = 0
    async with system_session() as db:
        sessions = (await db.execute(select(WhatsAppSession))).scalars().all()
        for sess in sessions:
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

            was_failed = sess.status == SessionStatus.failed
            sess.status = new_status
            if new_status == SessionStatus.failed and not was_failed:
                newly_failed += 1
                db.add(
                    Notification(
                        tenant_id=sess.tenant_id,
                        type=NotificationType.session_failed,
                        title="WhatsApp session disconnected",
                        body=f"Session '{sess.label or sess.session_name}' is FAILED.",
                        meta={"session_name": sess.session_name},
                    )
                )
                logger.bind(session=sess.session_name, tenant_id=str(sess.tenant_id)).error(
                    "session FAILED — notification recorded"
                )
    return newly_failed


__all__ = ["poll_session_health"]
