"""Set up the target resource on connect, so the owner never pastes an id.

This module is the whole point of the OAuth swap. Previously an owner had to find
a Calendar ID or Spreadsheet ID in a Google URL and paste it back into Qonvo;
here, connect *creates* the calendar and the Picker *hands over* the spreadsheet.

Google client libraries are imported lazily and every blocking call is offloaded
to a thread, matching ``calendar.py`` / ``sheets.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import logger
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from app.integrations.google_auth import build_service
from app.integrations.scopes import (
    QONVO_CALENDAR_SUMMARY,
    SCOPES,
)


class ProvisioningError(Exception):
    """The target calendar/spreadsheet could not be created or reached."""


def _calendar_service(access_token: str) -> Any:
    return build_service("calendar", "v3", access_token, SCOPES[GOOGLE_CALENDAR])


def _sheets_service(access_token: str) -> Any:
    return build_service("sheets", "v4", access_token, SCOPES[GOOGLE_SHEETS])


async def ensure_qonvo_calendar(
    access_token: str,
    *,
    existing_calendar_id: str | None,
    timezone: str,
) -> tuple[str, bool]:
    """Return ``(calendar_id, created)`` for Qonvo's bookings calendar.

    Idempotency keys on *reachability of the stored id*, not on matching a name in
    a calendar list: under ``calendar.app.created`` there is no dependable way to
    enumerate calendars, and name-matching would break the moment an owner renamed
    it. Probing the stored id also does the right thing when the owner reconnects
    a *different* Google account — the old id 404s, so a fresh calendar is made in
    the new account instead of writing bookings into a void.
    """
    service = _calendar_service(access_token)

    if existing_calendar_id:
        try:
            await asyncio.to_thread(
                lambda: service.calendars().get(calendarId=existing_calendar_id).execute()
            )
            return existing_calendar_id, False
        except Exception as exc:  # noqa: BLE001 — any failure means "make a new one"
            logger.info(f"stored calendar {existing_calendar_id} unreachable, recreating: {exc}")

    try:
        created = await asyncio.to_thread(
            lambda: service.calendars()
            .insert(body={"summary": QONVO_CALENDAR_SUMMARY, "timeZone": timezone})
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise ProvisioningError(f"could not create the Qonvo Bookings calendar: {exc}") from exc

    calendar_id = created.get("id")
    if not calendar_id:
        raise ProvisioningError("Google created a calendar but returned no id")
    return calendar_id, True


async def describe_spreadsheet(access_token: str, spreadsheet_id: str) -> tuple[str, list[str]]:
    """Return ``(title, tab_titles)``; doubles as the ``drive.file`` access check.

    Under per-file scope this only succeeds for a spreadsheet the owner actually
    selected through the Picker with this client id, so a failure here is the
    honest signal that the selection didn't grant access.
    """
    service = _sheets_service(access_token)
    try:
        meta = await asyncio.to_thread(
            lambda: service.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                includeGridData=False,
                fields="properties.title,sheets.properties.title",
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise ProvisioningError(
            f"couldn't open that spreadsheet — pick it again from the chooser: {exc}"
        ) from exc

    title = (meta.get("properties") or {}).get("title") or "Untitled spreadsheet"
    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    return title, tabs


async def create_spreadsheet(access_token: str, title: str) -> tuple[str, str, list[str]]:
    """Create a spreadsheet Qonvo owns access to. Returns ``(id, title, tabs)``.

    ``drive.file`` covers files the app creates as well as files the user picks,
    so this is the Picker-free path — useful for an owner who has no sheet yet and
    just wants leads logged somewhere.
    """
    service = _sheets_service(access_token)
    try:
        created = await asyncio.to_thread(
            lambda: service.spreadsheets()
            .create(
                body={"properties": {"title": title}},
                fields="spreadsheetId,properties.title,sheets.properties.title",
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise ProvisioningError(f"could not create a spreadsheet: {exc}") from exc

    spreadsheet_id = created.get("spreadsheetId")
    if not spreadsheet_id:
        raise ProvisioningError("Google created a spreadsheet but returned no id")
    resolved_title = (created.get("properties") or {}).get("title") or title
    tabs = [s["properties"]["title"] for s in created.get("sheets", [])] or ["Sheet1"]
    return spreadsheet_id, resolved_title, tabs


__all__ = [
    "ProvisioningError",
    "create_spreadsheet",
    "describe_spreadsheet",
    "ensure_qonvo_calendar",
]
