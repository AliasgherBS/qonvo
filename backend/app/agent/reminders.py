"""Booking reminders — capped, opt-out-aware outbound (DESIGN.md §5.7).

The ONLY bot-initiated messaging. Rules (§5.7):
- Only bookings made via an existing chat (``conversation_id`` present).
- Max 2 messages per booking: a confirmation + a 24h-before reminder, each tracked
  by its own timestamp column so a re-run never double-sends.
- Opt-out ("stop") honoured via ``reminder_suppressions``.
- Sent through the send gateway (paced, business-hours-only, daily-cap-counted).

Predicates + message rendering are pure so they unit-test without a DB/network;
:func:`dispatch_due_reminders` is the DB-backed orchestration the scheduler runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.enums import BookingStatus

STOP_KEYWORDS = {
    "stop",
    "unsubscribe",
    "stop reminders",
    "no reminders",
    "opt out",
    "optout",
    "band karo",  # ur: "stop it"
    "rok do",  # ur: "stop"
}


def is_stop_message(text: str | None) -> bool:
    """True if the customer is opting out of reminders."""
    if not text:
        return False
    normalized = text.strip().lower()
    return normalized in STOP_KEYWORDS or (
        len(normalized) <= 24 and any(k in normalized for k in ("unsubscribe", "stop remind"))
    )


def needs_confirmation(booking: Any, *, now: datetime) -> bool:
    return (
        booking.status != BookingStatus.cancelled
        and booking.conversation_id is not None
        and booking.confirmation_sent_at is None
        and booking.scheduled_at is not None
        and booking.scheduled_at > now
    )


def needs_reminder(booking: Any, *, now: datetime, lookahead_hours: int = 24) -> bool:
    return (
        booking.status != BookingStatus.cancelled
        and booking.conversation_id is not None
        and booking.reminder_sent_at is None
        and booking.scheduled_at is not None
        and now < booking.scheduled_at <= now + timedelta(hours=lookahead_hours)
    )


def _when(booking: Any) -> str:
    dt = booking.scheduled_at
    return dt.strftime("%A %d %b at %H:%M") if dt else "your appointment"


def render_confirmation(booking: Any) -> str:
    summary = (booking.data or {}).get("summary") or "your appointment"
    return (
        f"You're confirmed for {summary} on {_when(booking)}. "
        "We'll send a reminder the day before. Reply STOP to opt out of reminders."
    )


def render_reminder(booking: Any) -> str:
    summary = (booking.data or {}).get("summary") or "your appointment"
    return (
        f"Reminder: {summary} is coming up on {_when(booking)}. "
        "See you then! Reply STOP to opt out."
    )


@dataclass(slots=True)
class ReminderPlan:
    """One reminder to send: which booking, which kind, and the rendered text."""

    booking: Any
    kind: str  # "confirmation" | "reminder"
    text: str


def plan_for_booking(
    booking: Any, *, now: datetime, lookahead_hours: int = 24
) -> ReminderPlan | None:
    """Confirmation takes priority over the 24h reminder in a single pass."""
    if needs_confirmation(booking, now=now):
        return ReminderPlan(booking, "confirmation", render_confirmation(booking))
    if needs_reminder(booking, now=now, lookahead_hours=lookahead_hours):
        return ReminderPlan(booking, "reminder", render_reminder(booking))
    return None


def now_utc() -> datetime:
    return datetime.now(UTC)


async def dispatch_due_reminders(
    send_gateway: Any,
    *,
    now: datetime | None = None,
    lookahead_hours: int = 24,
    limit: int = 200,
) -> dict[str, int]:
    """Scan every tenant's bookings and send any due confirmation/reminder.

    Runs as the ``qonvo_system`` (BYPASSRLS) role — a trusted cross-tenant path
    (§3), like the scheduler's session-health scan. Respects opt-out, business
    hours, and the per-session daily cap.
    """
    from sqlalchemy import or_, select

    from app.core.logging import logger
    from app.core.tenancy import system_session
    from app.models.business import Booking, ReminderSuppression
    from app.models.conversation import Conversation
    from app.models.tenant import TenantConfig
    from app.models.whatsapp import WhatsAppSession
    from app.waha.send_gateway import DailyCapExceeded, SessionPacing
    from app.workers.pipeline import is_within_business_hours

    now = now or now_utc()
    stats = {"confirmation": 0, "reminder": 0, "skipped": 0}

    async with system_session() as db:
        bookings = (
            (
                await db.execute(
                    select(Booking)
                    .where(
                        Booking.status != BookingStatus.cancelled,
                        Booking.conversation_id.isnot(None),
                        Booking.scheduled_at.isnot(None),
                        Booking.scheduled_at > now,
                        or_(
                            Booking.confirmation_sent_at.is_(None),
                            Booking.reminder_sent_at.is_(None),
                        ),
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for booking in bookings:
            plan = plan_for_booking(booking, now=now, lookahead_hours=lookahead_hours)
            if plan is None:
                continue
            conv = await db.get(Conversation, booking.conversation_id)
            session_row = (
                await db.get(WhatsAppSession, conv.session_id) if conv is not None else None
            )
            if conv is None or session_row is None:
                stats["skipped"] += 1
                continue
            phone = booking.customer_phone
            if phone:
                suppressed = (
                    await db.execute(
                        select(ReminderSuppression).where(
                            ReminderSuppression.tenant_id == booking.tenant_id,
                            ReminderSuppression.phone == phone,
                        )
                    )
                ).scalar_one_or_none()
                if suppressed is not None:
                    stats["skipped"] += 1
                    continue
            tenant_config = (
                await db.execute(
                    select(TenantConfig).where(TenantConfig.tenant_id == booking.tenant_id)
                )
            ).scalar_one_or_none()
            business_hours = tenant_config.business_hours if tenant_config else {}
            if business_hours and not is_within_business_hours(business_hours, now=now):
                stats["skipped"] += 1  # closed — retry on a later scan
                continue

            pacing = SessionPacing(
                daily_cap=session_row.daily_cap, warmup_stage=session_row.warmup_stage
            )
            try:
                await send_gateway.send_text(
                    session_row.session_name, conv.chat_id, plan.text, pacing=pacing
                )
            except DailyCapExceeded:
                stats["skipped"] += 1
                continue
            except Exception as exc:  # noqa: BLE001 — one bad send must not stop the batch
                logger.warning(f"reminder send failed for booking {booking.id}: {exc}")
                stats["skipped"] += 1
                continue

            if plan.kind == "confirmation":
                booking.confirmation_sent_at = now
            else:
                booking.reminder_sent_at = now
            stats[plan.kind] += 1

    return stats


__all__ = [
    "ReminderPlan",
    "dispatch_due_reminders",
    "is_stop_message",
    "needs_confirmation",
    "needs_reminder",
    "now_utc",
    "plan_for_booking",
    "render_confirmation",
    "render_reminder",
]
