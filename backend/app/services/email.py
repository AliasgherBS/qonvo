"""Email transport for owner alerts (DESIGN.md §12.1).

Config-driven: ``QONVO_EMAIL_PROVIDER`` selects ``log`` (default — just logs, so
wiring is verifiable in dev without creds), ``resend`` (HTTP API), or ``smtp``.
Sending never raises into the caller — an alert that can't be emailed must not
break the flow that triggered it.
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.enums import UserRole
from app.models.tenant import TenantUser, User


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send one email via the configured transport. Returns True on success."""
    provider = (settings.email_provider or "log").lower()
    try:
        if provider == "resend" and settings.email_resend_api_key:
            return await _send_resend(to, subject, body)
        if provider == "smtp" and settings.email_smtp_host:
            return await asyncio.to_thread(_send_smtp, to, subject, body)
        # Default/dev: log transport — proves the wiring without external creds.
        logger.bind(to=to).info(f"[email:log] {subject}\n{body}")
        return True
    except Exception as exc:  # noqa: BLE001 — alert delivery must never raise
        logger.warning(f"email send failed ({provider}): {exc}")
        return False


async def _send_resend(to: str, subject: str, body: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.email_resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "text": body},
        )
        resp.raise_for_status()
    return True


def _send_smtp(to: str, subject: str, body: str) -> bool:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as server:
        if settings.email_smtp_starttls:
            server.starttls()
        if settings.email_smtp_user:
            server.login(settings.email_smtp_user, settings.email_smtp_password or "")
        server.send_message(msg)
    return True


async def email_owner(db: AsyncSession, tenant_id: uuid.UUID, subject: str, body: str) -> bool:
    """Email the tenant's owner. No-op (False) if no owner email is found."""
    email = (
        await db.execute(
            select(User.email)
            .join(TenantUser, TenantUser.user_id == User.id)
            .where(TenantUser.tenant_id == tenant_id, TenantUser.role == UserRole.owner)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not email:
        return False
    return await send_email(email, subject, body)


__all__ = ["email_owner", "send_email"]
