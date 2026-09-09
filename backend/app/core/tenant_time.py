"""What time it is for a tenant, resolved in one place (teardown B1, N1, V2).

Time was decided in three places and all three silently meant UTC:
``business_hours["timezone"]`` for the opening-hours gate, an integration's
``config["timezone"]`` for the calendar, and ``settings.google_default_timezone``
for the booking skills, which never consulted either of the other two. So an
owner who found the timezone select buried in the Google Calendar card and set
it correctly *still* got UTC bookings, because the skill that creates the event
did not read it.

One function, so a fourth place cannot quietly appear.

An invalid name is treated as UTC rather than raised. These values reach us from
a browser's ``resolvedOptions().timeZone`` and from hand-edited JSON, and a
tenant whose timezone string is a typo should get slightly wrong opening hours,
not a worker that crashes on every message.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.logging import logger

__all__ = [
    "DEFAULT_TIMEZONE",
    "is_valid_timezone",
    "local_now",
    "tenant_timezone",
    "tenant_zone",
]

DEFAULT_TIMEZONE = "UTC"

_UTC = ZoneInfo("UTC")


def is_valid_timezone(name: str | None) -> bool:
    """Whether this is an IANA name the runtime can actually load."""
    if not name or not isinstance(name, str):
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def tenant_timezone(tenant_config: object | None) -> str:
    """The tenant's timezone name.

    Falls back through the old locations before UTC, so a tenant whose value
    only ever existed inside the ``business_hours`` JSON is not reset to UTC by
    the very change meant to fix their clock. The migration promotes those, and
    this is the belt to that braces: a config row written by an older worker
    during a rolling deploy would otherwise read as UTC.
    """
    name = getattr(tenant_config, "timezone", None)
    # Not `if is_valid_timezone(name)`. UTC is a perfectly valid zone, so that
    # test returns on the column's own default and the legacy lookup below is
    # dead code -- which is what the first version of this did. UTC in the
    # column means "nobody has said", so a real value elsewhere wins.
    if is_valid_timezone(name) and name != DEFAULT_TIMEZONE:
        return name  # type: ignore[return-value]

    legacy = (getattr(tenant_config, "business_hours", None) or {}).get("timezone")
    if is_valid_timezone(legacy) and legacy != DEFAULT_TIMEZONE:
        return legacy

    if name and name != DEFAULT_TIMEZONE:
        # Worth a line in the log: it means somebody stored a name we cannot
        # load, and their opening hours are silently an hour or five out.
        logger.warning(f"unknown tenant timezone {name!r}, using {DEFAULT_TIMEZONE}")
    return DEFAULT_TIMEZONE


def tenant_zone(tenant_config: object | None) -> tzinfo:
    """The tenant's timezone as a ``tzinfo``, ready to convert against."""
    try:
        return ZoneInfo(tenant_timezone(tenant_config))
    except (ZoneInfoNotFoundError, ValueError):
        return _UTC


def local_now(tenant_config: object | None, *, now: datetime) -> datetime:
    """``now`` expressed in the tenant's own clock."""
    return now.astimezone(tenant_zone(tenant_config))
