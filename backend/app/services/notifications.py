"""Owner WhatsApp alerts + dashboard notification log (DESIGN.md §5.5, §12.1).

MVP notification transport is a WhatsApp message to the owner's own number
(``tenant_config.owner_alert_number``), sent through the single send gateway
(never the raw WAHA client — §5.6), plus an always-written ``notifications``
row for the dashboard log. Email transport is Phase 3.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
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


__all__ = ["notify"]
