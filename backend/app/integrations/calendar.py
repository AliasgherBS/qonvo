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

    async def free_busy(
        self, *, time_min: datetime, time_max: datetime, calendar_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Busy blocks across the owner's calendars, as ``{"start","end"}`` dicts.

        This exists because the ``calendar.app.created`` scope makes
        ``list_events`` blind to everything Qonvo didn't book itself — so on its
        own it would happily book a customer over the owner's dentist appointment.
        ``freebusy`` reaches ``primary`` under the companion ``calendar.freebusy``
        scope and returns opaque busy windows (no titles), which is all an
        availability check needs.

        Not part of the :class:`CalendarClient` Protocol on purpose: callers probe
        for it with ``getattr`` so injected fakes and a future
        ``calendar.events`` upgrade both keep working without it.
        """
        ids = calendar_ids or ["primary", self._calendar_id]
        resp = await asyncio.to_thread(
            lambda: self._service.freebusy()
            .query(
                body={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "items": [{"id": cid} for cid in ids],
                }
            )
            .execute()
        )
        out: list[dict[str, Any]] = []
        for entry in (resp.get("calendars") or {}).values():
            for block in entry.get("busy", []):
                out.append({"start": block.get("start"), "end": block.get("end")})
        out.sort(key=lambda b: b["start"] or "")
        return out

    async def ping(self) -> None:
        """Cheap read to verify the grant is live and the calendar is reachable."""
        await asyncio.to_thread(
            lambda: self._service.events()
            .list(calendarId=self._calendar_id, maxResults=1)
            .execute()
        )


__all__ = ["CalendarClient", "GoogleCalendarClient"]
