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
    host, port = settings.email_smtp_host, settings.email_smtp_port
    # Port 465 = implicit SSL (SMTPS): the whole connection is TLS from the start.
    # Prefer it where a network intercepts STARTTLS on 587 (the handshake stalls) —
    # verified live on this VPS/WSL host. Other ports use SMTP + optional STARTTLS.
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if port != 465 and settings.email_smtp_starttls:
            server.starttls()
        if settings.email_smtp_user:
            server.login(settings.email_smtp_user, settings.email_smtp_password or "")
        server.send_message(msg)
    return True


async def send_welcome_email(to: str, name: str | None, business: str) -> bool:
    """Onboarding welcome email sent right after signup."""
    hello = f"Hi {name}," if name else "Hi there,"
    body = (
        f"{hello}\n\n"
        f"Welcome to Qonvo — your AI WhatsApp rep for {business} is ready to set up.\n\n"
        "Next steps:\n"
        "  1. Connect your WhatsApp number (scan the QR).\n"
        "  2. Add what your rep should know (hours, prices, policies).\n"
        "  3. Message the number to see it reply.\n\n"
        f"Open your dashboard: {settings.dashboard_base_url}\n\n"
        "You're on a 14-day free trial. Reply to this email if you need a hand.\n\n"
        "— The Qonvo team"
    )
    return await send_email(to, "Welcome to Qonvo 👋", body)


async def send_password_reset_email(to: str, name: str | None, reset_url: str) -> bool:
    """Password-reset link email (link expires in 30 minutes)."""
    hello = f"Hi {name}," if name else "Hi there,"
    body = (
        f"{hello}\n\n"
        "We received a request to reset your Qonvo password. Click the link below "
        "to choose a new one — it expires in 30 minutes:\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email; your "
        "password won't change.\n\n"
        "— The Qonvo team"
    )
    return await send_email(to, "Reset your Qonvo password", body)


async def send_team_invite_email(to: str, business: str, role: str, accept_url: str) -> bool:
    """Invite email with the accept link (link expires in 7 days)."""
    body = (
        "Hi there,\n\n"
        f"You've been invited to join {business} on Qonvo as {role}. "
        "Qonvo is the AI WhatsApp rep that answers customers for the business.\n\n"
        "Accept your invitation and set up your account here (expires in 7 days):\n\n"
        f"{accept_url}\n\n"
        "If you weren't expecting this, you can ignore this email.\n\n"
        "— The Qonvo team"
    )
    return await send_email(to, f"You're invited to {business} on Qonvo", body)


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


__all__ = [
    "email_owner",
    "send_email",
    "send_password_reset_email",
    "send_welcome_email",
]
