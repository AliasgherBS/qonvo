"""``check_availability`` skill: read the calendar for a day's busy times (§7).

Lets the rep answer "are you free Tuesday at 3pm?" from the real calendar instead
of guessing. Read-only; requires the ``google_calendar`` integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.integrations import GOOGLE_CALENDAR
from app.integrations.resolver import resolve_integration_client
from app.skills.registry import SkillContext, SkillDefinition

_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "date": {
            "type": "string",
            "description": "The day to check, as YYYY-MM-DD.",
        },
        "timezone": {
            "type": "string",
            "description": "IANA timezone (e.g. 'Asia/Karachi') if different from the default.",
        },
    },
    "required": ["date"],
}


async def handle(ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    client = await resolve_integration_client(ctx, GOOGLE_CALENDAR)
    if client is None:
        return {"status": "error", "message": "The calendar isn't connected yet."}

    date_str = (args.get("date") or "").strip()
    tz_name = (args.get("timezone") or "").strip() or settings.google_default_timezone
    try:
        tz = ZoneInfo(tz_name)
        day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    except (ValueError, KeyError):
        return {"status": "error", "message": f"Couldn't understand the date '{date_str}'."}

    events = await client.list_events(time_min=day, time_max=day + timedelta(days=1))
    busy = [
        {"summary": e.get("summary") or "Busy", "start": e.get("start"), "end": e.get("end")}
        for e in events
    ]
    return {
        "status": "ok",
        "date": date_str,
        "busy": busy,
        "message": (
            f"{len(busy)} appointment(s) already booked on {date_str}."
            if busy
            else f"The calendar is completely open on {date_str}."
        ),
    }


DEFINITION = SkillDefinition(
    name="check_availability",
    description=(
        "Check the business calendar for existing appointments on a given day "
        "before offering or confirming a time. Use this instead of guessing "
        "availability; then book with book_appointment."
    ),
    parameters=_PARAMETERS,
    handler=handle,
    requires_integration=GOOGLE_CALENDAR,
)

__all__ = ["DEFINITION", "handle"]
