"""One clock per tenant (teardown B1, N1, V2).

Time was decided in three places and all three silently meant UTC:
``business_hours["timezone"]``, which the client sent as the literal string
``"UTC"`` with no control bound to it; the Google Calendar integration's own
``config["timezone"]``, unreachable for a tenant with no Google account; and
``settings.google_default_timezone``, which is what the booking skills actually
read, so they ignored the other two entirely.

The two tests worth reading are the business-hours one, which reproduces "the
rep refuses to talk to customers during business hours", and the booking one,
which reproduces "3 PM becomes 8 PM on the owner's real calendar". Both were
silent: nothing logged, nothing on any screen.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from app.core.tenant_time import (
    DEFAULT_TIMEZONE,
    is_valid_timezone,
    local_now,
    tenant_timezone,
    tenant_zone,
)

KARACHI = ZoneInfo("Asia/Karachi")

NINE_TO_FIVE = {
    "enabled": True,
    "hours": {day: [["09:00", "17:00"]] for day in ("mon", "tue", "wed", "thu", "fri")},
}


def config(timezone: str | None = None, business_hours: dict | None = None):
    return SimpleNamespace(timezone=timezone, business_hours=business_hours or {})


# --- resolution order ------------------------------------------------------------- #
def test_the_configured_timezone_is_used():
    assert tenant_timezone(config("Asia/Karachi")) == "Asia/Karachi"


def test_a_value_left_in_the_old_business_hours_json_is_still_honoured():
    """The migration promotes these, and this is the belt to that braces. A
    config row written by an older worker mid-deploy would otherwise read as
    UTC and put the tenant's clock back where it was."""
    assert tenant_timezone(config("UTC", {"timezone": "Asia/Dubai"})) == "Asia/Dubai"


def test_the_column_wins_when_both_are_real():
    assert tenant_timezone(config("Asia/Karachi", {"timezone": "Asia/Dubai"})) == "Asia/Karachi"


def test_utc_in_the_column_does_not_shadow_a_real_legacy_value():
    """The bug in the first version of this resolver. ``UTC`` is a valid zone,
    so testing validity alone returned on the column's own default and the
    legacy lookup was dead code."""
    assert tenant_timezone(config("UTC", {"timezone": "Asia/Karachi"})) == "Asia/Karachi"


@pytest.mark.parametrize("bad", [None, "", "Mars/Olympus", "not a zone", 5, "UTC+5"])
def test_an_unusable_value_falls_back_rather_than_raising(bad):
    """These arrive from a browser and from hand-edited JSON. A typo should
    cost slightly wrong opening hours, not a worker that dies on every
    message."""
    assert tenant_timezone(config(bad)) == DEFAULT_TIMEZONE


def test_no_config_at_all_is_utc():
    assert tenant_timezone(None) == DEFAULT_TIMEZONE
    assert tenant_zone(None) == ZoneInfo("UTC")


@pytest.mark.parametrize(
    "name,valid",
    [("Asia/Karachi", True), ("UTC", True), ("Europe/London", True), ("Nowhere/Nothing", False)],
)
def test_the_validator(name, valid):
    assert is_valid_timezone(name) is valid


def test_local_now_converts():
    noon_utc = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.UTC)

    assert local_now(config("Asia/Karachi"), now=noon_utc).hour == 17


# --- B1: the rep refusing customers during business hours -------------------------- #
def test_business_hours_are_evaluated_in_the_tenants_timezone():
    """The finding. 05:00 UTC on a Tuesday is 10:00 in Karachi, which is inside
    a 9-to-5 week. Read as UTC it is four hours before opening, so the rep
    answers "we're closed right now" to a customer standing in the shop."""
    from app.workers.pipeline import is_within_business_hours

    five_am_utc = dt.datetime(2026, 9, 8, 5, 0, tzinfo=dt.UTC)  # a Tuesday

    assert (
        is_within_business_hours(
            NINE_TO_FIVE, now=five_am_utc, tenant_config=config("Asia/Karachi")
        )
        is True
    )
    # And the old behaviour, for contrast: the same instant with no timezone.
    assert is_within_business_hours(NINE_TO_FIVE, now=five_am_utc, tenant_config=config()) is False


def test_the_evening_is_closed_in_the_tenants_timezone_too():
    """Over-correcting would be its own bug: the gate has to still close."""
    from app.workers.pipeline import is_within_business_hours

    six_pm_karachi = dt.datetime(2026, 9, 8, 13, 0, tzinfo=dt.UTC)  # 18:00 PKT

    assert (
        is_within_business_hours(
            NINE_TO_FIVE, now=six_pm_karachi, tenant_config=config("Asia/Karachi")
        )
        is False
    )


def test_disabled_hours_are_always_open_whatever_the_clock():
    from app.workers.pipeline import is_within_business_hours

    assert (
        is_within_business_hours(
            {**NINE_TO_FIVE, "enabled": False},
            now=dt.datetime(2026, 9, 8, 2, 0, tzinfo=dt.UTC),
            tenant_config=config("Asia/Karachi"),
        )
        is True
    )


def test_existing_callers_without_a_config_still_read_the_legacy_key():
    """Dozens of call sites pass no config. They must keep behaving as they
    did, which means falling back to the timezone inside the dict."""
    from app.workers.pipeline import is_within_business_hours

    five_am_utc = dt.datetime(2026, 9, 8, 5, 0, tzinfo=dt.UTC)

    assert (
        is_within_business_hours({**NINE_TO_FIVE, "timezone": "Asia/Karachi"}, now=five_am_utc)
        is True
    )


# --- N1: the booking skills never read the tenant's clock -------------------------- #
def test_the_booking_skills_read_the_tenant_not_the_system_default():
    """They took ``settings.google_default_timezone``, a global "UTC", so an
    owner who set the timezone on the Google Calendar card still got UTC
    events. Asserted against the parsed source rather than by running the
    skill, which needs a live Google client."""
    import ast
    import inspect

    from app.skills import book_appointment, check_availability

    for module in (book_appointment, check_availability):
        tree = ast.parse(inspect.getsource(module))
        handler = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle"
        )
        body = ast.unparse(handler)
        assert "tenant_timezone(ctx.tenant_config)" in body, module.__name__
        assert "settings.google_default_timezone" not in body, module.__name__


# --- V2: the setting is reachable without a Google account ------------------------- #
def test_the_config_api_exposes_and_validates_the_timezone():
    """The cause rather than the symptom: the one setting governing both
    opening hours and bookings used to live inside an optional integration."""
    from app.api.config import ConfigResponse, ConfigUpdateRequest

    assert "timezone" in ConfigUpdateRequest.model_fields
    assert "timezone" in ConfigResponse.model_fields


def test_an_unknown_timezone_is_refused_rather_than_stored():
    """Storing it would resolve back to UTC, so the owner would see their
    choice saved and their opening hours still wrong -- the same invisible
    failure this whole change fixes."""
    from app.api.config import ConfigUpdateRequest, _apply_config_update
    from fastapi import HTTPException

    row = SimpleNamespace(timezone="UTC", providers={}, escalation_rules={})

    with pytest.raises(HTTPException) as caught:
        _apply_config_update(row, ConfigUpdateRequest(timezone="Mars/Olympus"))

    assert caught.value.status_code == 400
    assert row.timezone == "UTC"


def test_a_known_timezone_is_applied():
    from app.api.config import ConfigUpdateRequest, _apply_config_update

    row = SimpleNamespace(timezone="UTC", providers={}, escalation_rules={})

    _apply_config_update(row, ConfigUpdateRequest(timezone="Asia/Karachi"))

    assert row.timezone == "Asia/Karachi"


def test_signup_accepts_the_browsers_timezone():
    """Taken at signup so a new tenant is correct without anyone visiting a
    settings page, which is where the UTC default did its damage."""
    from app.api.auth import SignupRequest

    assert "timezone" in SignupRequest.model_fields
    assert SignupRequest.model_fields["timezone"].default is None
