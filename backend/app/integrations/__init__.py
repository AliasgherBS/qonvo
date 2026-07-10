"""Third-party integrations: Google Calendar + Sheets (DESIGN.md §7).

Credentials are Google *service-account* keys. A tenant shares their Calendar or
Sheet with the service-account email, so there is no per-user OAuth flow — which
keeps the product "fully-managed, owner never runs code". Per-tenant keys live
(Fernet-encrypted) in the ``integrations`` table and override the system-default
key in settings.
"""

from __future__ import annotations

GOOGLE_CALENDAR = "google_calendar"
GOOGLE_SHEETS = "google_sheets"

SUPPORTED_PROVIDERS = (GOOGLE_CALENDAR, GOOGLE_SHEETS)

__all__ = ["GOOGLE_CALENDAR", "GOOGLE_SHEETS", "SUPPORTED_PROVIDERS"]
