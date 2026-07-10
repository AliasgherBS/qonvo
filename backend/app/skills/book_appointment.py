"""``book_appointment`` skill: create a Google Calendar event + Booking (§7).

Idempotent through the ``skill_executions`` ledger (see registry.execute_skill),
so an at-least-once redelivery never double-books. Requires the tenant's
``google_calendar`` integration to be connected — the registry hides this tool
otherwise, so the handler's "not connected" branch is a defensive fallback.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.integrations import GOOGLE_CALENDAR
from app.integrations.resolver import resolve_integration_client
from app.models.business import Booking
from app.models.enums import BookingStatus
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Short title for the appointment (e.g. 'Haircut — Ali').",
        },
        "start_time": {
            "type": "string",
            "description": (
                "Appointment start as ISO 8601. Include the timezone offset when "
                "known (e.g. '2026-07-12T15:00:00+05:00'); otherwise the "
                "business's configured timezone is assumed."
            ),
        },
        "duration_minutes": {
            "type": "integer",
            "description": "Length in minutes. Omit to use the business default.",
        },
        "end_time": {
            "type": "string",
            "description": "Optional explicit end (ISO 8601); overrides duration_minutes.",
        },
        "customer_name": {"type": "string", "description": "Customer's name, if known."},
        "customer_phone": {
            "type": "string",
            "description": "Customer's phone; defaults to the current chat's number.",
        },
        "notes": {"type": "string", "description": "Anything else to record on the booking."},
        "timezone": {
            "type": "string",
            "description": "IANA timezone (e.g. 'Asia/Karachi') if it differs from the default.",
        },
    },
    "required": ["summary", "start_time"],
}


def _phone_from_chat_id(chat_id: str | None) -> str | None:
    if not chat_id:
        return None
    return chat_id.split("@", 1)[0] or None


def _parse_iso(value: str, tz_name: str) -> datetime:
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    client = await resolve_integration_client(ctx, GOOGLE_CALENDAR)
    if client is None:
        return {"status": "error", "message": "The calendar isn't connected yet."}

    summary = (args.get("summary") or "").strip() or "Appointment"
    start_raw = (args.get("start_time") or "").strip()
    if not start_raw:
        return {"status": "error", "message": "A start time is required to book."}

    tz_name = (args.get("timezone") or "").strip() or settings.google_default_timezone
    try:
        start = _parse_iso(start_raw, tz_name)
    except ValueError:
        return {"status": "error", "message": f"Couldn't understand the start time '{start_raw}'."}

    end_raw = (args.get("end_time") or "").strip()
    if end_raw:
        try:
            end = _parse_iso(end_raw, tz_name)
        except ValueError:
            return {"status": "error", "message": f"Couldn't understand the end time '{end_raw}'."}
    else:
        duration = args.get("duration_minutes") or settings.booking_default_duration_minutes
        end = start + timedelta(minutes=int(duration))

    customer_name = (args.get("customer_name") or "").strip() or None
    customer_phone = (args.get("customer_phone") or "").strip() or _phone_from_chat_id(ctx.chat_id)
    notes = (args.get("notes") or "").strip() or None

    description_lines = []
    if customer_name:
        description_lines.append(f"Customer: {customer_name}")
    if customer_phone:
        description_lines.append(f"Phone: {customer_phone}")
    if notes:
        description_lines.append(notes)
    description_lines.append("Booked by Qonvo.")

    event = await client.create_event(
        summary=summary,
        start=start,
        end=end,
        timezone=tz_name,
        description="\n".join(description_lines),
    )

    booking = Booking(
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        customer_phone=customer_phone,
        status=BookingStatus.confirmed,
        scheduled_at=start,
        external_event_id=event.get("id"),
        data={
            "summary": summary,
            "customer_name": customer_name,
            "notes": notes,
            "end": end.isoformat(),
            "html_link": event.get("html_link"),
        },
    )
    ctx.db.add(booking)
    await ctx.db.flush()

    return {
        "status": "booked",
        "booking_id": str(booking.id),
        "event_id": event.get("id"),
        "scheduled_at": start.isoformat(),
        "message": (
            f"You're booked for {summary} on "
            f"{start.strftime('%A %d %b at %H:%M')}. See you then!"
        ),
    }


DEFINITION = SkillDefinition(
    name="book_appointment",
    description=(
        "Book an appointment on the business calendar once you have a clear date "
        "and time. Confirm the time with the customer first. Do not invent "
        "availability — if unsure whether a slot is free, hand off to a human."
    ),
    parameters=_PARAMETERS,
    handler=handle,
    requires_integration=GOOGLE_CALENDAR,
)

__all__ = ["DEFINITION", "handle"]
