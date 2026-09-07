"""Email transport for owner alerts (DESIGN.md §12.1).

Config-driven: ``QONVO_EMAIL_PROVIDER`` selects ``log`` (default — just logs, so
wiring is verifiable in dev without creds), ``resend`` (HTTP API), or ``smtp``.
Sending never raises into the caller — an alert that can't be emailed must not
break the flow that triggered it.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
import time
import uuid
from email.message import EmailMessage

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.enums import UserRole
from app.models.tenant import Tenant, TenantUser, User
from app.services import email_templates as templates


async def send_email(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Send one email via the configured transport. Returns True on success.

    ``body`` is the plain-text part (always sent); ``html`` is an optional branded
    HTML alternative (multipart/alternative). Clients that can render HTML show it;
    the rest fall back to the text.

    ``reply_to`` defaults to ``QONVO_EMAIL_REPLY_TO``. Every email Qonvo sends
    comes from a no-reply address on a sending subdomain with no mailbox behind
    it, so without this a reply is silently discarded: the sender sees it leave,
    and nobody ever receives it.
    """
    provider = (settings.email_provider or "log").lower()
    reply_to = reply_to or settings.email_reply_to
    try:
        if provider == "resend" and settings.email_resend_api_key:
            return await _send_resend(to, subject, body, html, reply_to)
        if provider == "smtp" and settings.email_smtp_host:
            return await asyncio.to_thread(_send_smtp, to, subject, body, html, reply_to)
        # Default/dev: log transport — proves the wiring without external creds.
        logger.bind(to=to).info(f"[email:log] {subject} (reply-to: {reply_to or '-'})\n{body}")
        return True
    except Exception as exc:  # noqa: BLE001 — alert delivery must never raise
        logger.warning(f"email send failed ({provider}): {exc}")
        return False


async def _send_resend(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "text": body}
    if html:
        payload["html"] = html
    if reply_to:
        payload["reply_to"] = reply_to
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.email_resend_api_key}"},
            json=payload,
        )
        resp.raise_for_status()
    return True


def _send_smtp(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    host, port = settings.email_smtp_host, settings.email_smtp_port

    def _once() -> None:
        # Port 465 = implicit SSL (SMTPS): the whole connection is TLS from the start.
        # Prefer it where a network intercepts STARTTLS on 587 (the handshake stalls) —
        # verified live on this VPS/WSL host. Other ports use SMTP + optional STARTTLS.
        server = (
            smtplib.SMTP_SSL(host, port, timeout=30)
            if port == 465
            else smtplib.SMTP(host, port, timeout=30)
        )
        with server:
            if port != 465 and settings.email_smtp_starttls:
                server.starttls()
            if settings.email_smtp_user:
                server.login(settings.email_smtp_user, settings.email_smtp_password or "")
            server.send_message(msg)

    # The TLS handshake to Gmail intermittently times out on this network; a single
    # retry clears the transient case (observed live). Last failure re-raises.
    last: Exception | None = None
    for attempt in range(3):
        try:
            _once()
            return True
        except (smtplib.SMTPServerDisconnected, OSError, TimeoutError, ssl.SSLError) as exc:
            last = exc
            logger.bind(to=to).info(f"smtp attempt {attempt + 1} failed, retrying: {exc}")
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("smtp send failed")


async def send_welcome_email(to: str, name: str | None, business: str) -> bool:
    """Onboarding welcome email sent right after signup."""
    subject, text, html = templates.welcome(name, business, settings.dashboard_base_url)
    return await send_email(to, subject, text, html=html)


async def send_password_reset_email(to: str, name: str | None, reset_url: str) -> bool:
    """Password-reset link email (link expires in 30 minutes)."""
    subject, text, html = templates.password_reset(name, reset_url)
    return await send_email(to, subject, text, html=html)


async def send_team_invite_email(to: str, business: str, role: str, accept_url: str) -> bool:
    """Invite email with the accept link (link expires in 7 days)."""
    subject, text, html = templates.team_invite(business, role, accept_url)
    return await send_email(to, subject, text, html=html)


async def send_plan_upgraded_email(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    plan_key: str,
    amount_cents: int | None = None,
    currency: str | None = None,
    invoice_number: str | None = None,
) -> bool:
    """Confirm a paid plan to the tenant's owner.

    Not a receipt. The merchant of record is the seller, issues the invoice and
    emails its own confirmation with a portal link; a second document for one
    sale would be wrong rather than merely redundant. This says the thing the
    provider's receipt cannot: what the product now does.
    """
    from app.billing.plans import PLANS

    row = (
        await db.execute(
            select(User.email, Tenant.name)
            .join(TenantUser, TenantUser.user_id == User.id)
            .join(Tenant, Tenant.id == TenantUser.tenant_id)
            .where(TenantUser.tenant_id == tenant_id, TenantUser.role == UserRole.owner)
            .limit(1)
        )
    ).first()
    if row is None or not row.email:
        return False

    plan = PLANS.get(plan_key)
    subject, text, html = templates.plan_upgraded(
        business=row.name or "Your business",
        plan_name=plan.name if plan else plan_key.title(),
        plan_key=plan_key,
        dashboard_url=settings.dashboard_base_url,
        amount_cents=amount_cents,
        currency=currency,
        invoice_number=invoice_number,
    )
    return await send_email(row.email, subject, text, html=html)


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
    return await send_email(email, subject, body, html=templates.owner_alert(subject, body))


__all__ = [
    "email_owner",
    "send_plan_upgraded_email",
    "send_email",
    "send_password_reset_email",
    "send_welcome_email",
]
