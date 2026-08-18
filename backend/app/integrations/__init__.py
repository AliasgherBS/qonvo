"""Third-party integrations: Google Calendar + Sheets (DESIGN.md §7).

Credentials are per-tenant Google *user* OAuth grants: the owner clicks Connect,
consents, and Qonvo stores the resulting refresh token Fernet-encrypted in the
``integrations`` table. Nothing to copy, paste, or share by hand — which is what
keeps the product "fully-managed, owner never runs code".

Scope choice keeps every provider off Google's sensitive-scope review path (see
``scopes``): Sheets uses per-file ``drive.file`` (the file the owner picks), and
Calendar writes to a secondary calendar Qonvo creates in the owner's account.
"""

from __future__ import annotations

GOOGLE_CALENDAR = "google_calendar"
GOOGLE_SHEETS = "google_sheets"

SUPPORTED_PROVIDERS = (GOOGLE_CALENDAR, GOOGLE_SHEETS)

__all__ = ["GOOGLE_CALENDAR", "GOOGLE_SHEETS", "SUPPORTED_PROVIDERS"]
