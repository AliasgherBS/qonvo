"""OAuth scopes per provider, chosen to avoid Google's sensitive-scope review.

Two deliberate choices, both of which trade a little capability for shipping
without a 10-day verification round-trip:

* **Sheets** uses ``drive.file`` — non-sensitive, and a documented valid scope for
  ``spreadsheets.values.append``. It grants access only to files the owner picks
  through the Google Picker with *this* client id. A hand-typed spreadsheet id is
  therefore unreachable (404), which is why the target is set via ``/select`` and
  is not owner-writable config.
* **Calendar** uses ``calendar.app.created``, which can only see calendars this
  app made. Connect provisions a "Qonvo Bookings" secondary calendar in the
  owner's account. Because that scope is blind to the owner's *real*
  commitments, ``calendar.freebusy`` rides along so availability checks can see
  busy blocks on ``primary`` and avoid double-booking over them.

Upgrading Calendar to the owner's own calendar later is a one-line change: point
``CALENDAR_SCOPE`` at ``.../auth/calendar.events``. ``CALENDAR_PROVISIONS_OWN``
then goes False (connect stops provisioning, ``calendar_id`` becomes owner-set),
and every already-stored grant fails the ``REQUIRED_SCOPES`` subset check, so the
dashboard shows "Reconnect" without any migration.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
CALENDAR_FREEBUSY_SCOPE = "https://www.googleapis.com/auth/calendar.freebusy"
SHEETS_SCOPE = "https://www.googleapis.com/auth/drive.file"

# Requested alongside everything so the stored grant can name the connected
# account in the dashboard ("Booking into … in owner@gmail.com").
IDENTITY_SCOPES: tuple[str, ...] = ("openid", "email")

SCOPES: dict[str, tuple[str, ...]] = {
    GOOGLE_CALENDAR: (CALENDAR_SCOPE, CALENDAR_FREEBUSY_SCOPE, *IDENTITY_SCOPES),
    GOOGLE_SHEETS: (SHEETS_SCOPE, *IDENTITY_SCOPES),
}

# Scopes that must appear in the *granted* set for the integration to work.
# Google allows partial consent, so this is checked against what came back, never
# against what we asked for. openid/email are cosmetic and freebusy only degrades
# availability accuracy, so unchecking either must not brick the integration.
REQUIRED_SCOPES: dict[str, frozenset[str]] = {
    GOOGLE_CALENDAR: frozenset({CALENDAR_SCOPE}),
    GOOGLE_SHEETS: frozenset({SHEETS_SCOPE}),
}

# True while the calendar scope can only reach calendars this app created, i.e.
# connect must provision "Qonvo Bookings" and ``calendar_id`` is system-owned.
CALENDAR_PROVISIONS_OWN = CALENDAR_SCOPE.endswith("calendar.app.created")

QONVO_CALENDAR_SUMMARY = "Qonvo Bookings"


def scopes_for(provider: str) -> tuple[str, ...]:
    return SCOPES.get(provider, ())


def missing_scopes(provider: str, granted: Iterable[str]) -> frozenset[str]:
    """Required scopes absent from ``granted`` — empty means the grant is usable."""
    return REQUIRED_SCOPES.get(provider, frozenset()) - frozenset(granted)


def supports_freebusy(granted: Iterable[str]) -> bool:
    """Whether availability checks can consult the owner's real busy blocks."""
    return CALENDAR_FREEBUSY_SCOPE in frozenset(granted)


__all__ = [
    "CALENDAR_FREEBUSY_SCOPE",
    "CALENDAR_PROVISIONS_OWN",
    "CALENDAR_SCOPE",
    "IDENTITY_SCOPES",
    "QONVO_CALENDAR_SUMMARY",
    "REQUIRED_SCOPES",
    "SCOPES",
    "SHEETS_SCOPE",
    "missing_scopes",
    "scopes_for",
    "supports_freebusy",
]
