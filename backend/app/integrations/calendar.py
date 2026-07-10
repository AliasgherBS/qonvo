"""Google Calendar client — create events for ``book_appointment`` (DESIGN.md §7).

The real client wraps a google-api ``service`` resource and offloads its blocking
calls to a thread. Handlers depend on the :class:`CalendarClient` Protocol so
tests inject a fake without touching Google.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CalendarClient(Protocol):
    async def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        timezone: str,
        description: str | None = None,
        attendee_emails: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def list_events(
        self, *, time_min: datetime, time_max: datetime
    ) -> list[dict[str, Any]]: ...

    async def ping(self) -> None: ...


class GoogleCalendarClient:
    """Adapter over a ``calendar/v3`` service bound to one ``calendar_id``."""

    def __init__(self, service: Any, calendar_id: str, *, default_timezone: str = "UTC") -> None:
        self._service = service
        self._calendar_id = calendar_id
        self._default_timezone = default_timezone

    async def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        timezone: str,
        description: str | None = None,
        attendee_emails: list[str] | None = None,
    ) -> dict[str, Any]:
        tz = timezone or self._default_timezone
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        }
        if description:
            body["description"] = description
        if attendee_emails:
            body["attendees"] = [{"email": e} for e in attendee_emails]

        event = await asyncio.to_thread(
            lambda: self._service.events()
            .insert(calendarId=self._calendar_id, body=body)
            .execute()
        )
        return {
            "id": event.get("id"),
            "html_link": event.get("htmlLink"),
            "start": (event.get("start") or {}).get("dateTime"),
        }

    async def list_events(
        self, *, time_min: datetime, time_max: datetime
    ) -> list[dict[str, Any]]:
        """Events overlapping [time_min, time_max), expanded and time-ordered.

        Used by ``check_availability`` to compute busy windows.
        """
        resp = await asyncio.to_thread(
            lambda: self._service.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        out: list[dict[str, Any]] = []
        for e in resp.get("items", []):
            start = (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date")
            end = (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date")
            out.append({"summary": e.get("summary"), "start": start, "end": end})
        return out

    async def ping(self) -> None:
        """Cheap read to verify the key is valid and the calendar is shared with it."""
        await asyncio.to_thread(
            lambda: self._service.events()
            .list(calendarId=self._calendar_id, maxResults=1)
            .execute()
        )


__all__ = ["CalendarClient", "GoogleCalendarClient"]
