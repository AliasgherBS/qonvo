"""The WhatsApp page's API contract (teardown W1, W2, N3).

The page was setup-only: a tenant with a linked number that had received
messages two days ago saw the same empty connect form as a brand new one, and
the only place a dropped session could be restarted was the internal admin
console. These tests hold the shape that makes it a status page instead --
number, state, last event, restart, re-link -- and hold the connect form to
asking a human question rather than for a WAHA session key.

Hermetic: the database and WAHA are both stubs, so nothing here needs Postgres.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api import sessions as S
from app.api.deps import require_owner, require_verified_owner
from app.models.enums import SessionStatus
from app.models.whatsapp import WhatsAppSession
from app.waha.client import WahaError


def _row(**overrides) -> WhatsAppSession:
    row = WhatsAppSession(
        tenant_id=uuid.uuid4(),
        session_name="front-desk-abcd1234",
        label="Front desk",
        status=SessionStatus.working,
        engine="WEBJS",
        hmac_secret="s",
        daily_cap=500,
        warmup_stage=1,
    )
    row.id = overrides.pop("id", uuid.uuid4())
    row.created_at = overrides.pop("created_at", datetime(2026, 9, 1, tzinfo=UTC))
    row.phone_number = overrides.pop("phone_number", None)
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _db(row: WhatsAppSession, last_event: datetime | None = None) -> AsyncMock:
    """A session that answers the two queries the routes make.

    The first ``execute`` is the session lookup, the second is the grouped
    last-activity query.
    """
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = row
    lookup.scalars.return_value.all.return_value = [row]

    activity = MagicMock()
    activity.all.return_value = [(row.id, last_event)] if last_event else []

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[lookup, activity])
    # Sync on a real session; an AsyncMock here leaves audit.record's row as an
    # un-awaited coroutine and the test warns instead of asserting.
    db.add = MagicMock()
    return db


# --- W2: the form stops asking for an internal identifier ----------------------- #
def test_creating_a_session_requires_no_fields():
    """`session_name` used to be required, and the form asked a salon owner to
    invent one with the example `main-support-line`. It is the WAHA session key,
    which the route derives anyway."""
    body = S.CreateSessionRequest()
    assert body.label is None
    assert body.session_name is None
    assert body.display_label == S.DEFAULT_SESSION_LABEL


def test_a_human_label_becomes_the_session_key():
    name = S.derive_session_name("Front desk")
    assert name.startswith("front-desk-")
    # Globally unique: one WAHA serves every tenant, so two tenants naming a
    # number "Front desk" must not collide.
    assert S.derive_session_name("Front desk") != name


def test_a_label_of_only_punctuation_still_yields_a_usable_key():
    """The slug is regex-stripped, so a label like "!!!" empties out. An empty
    WAHA session name is a 422 from WAHA, i.e. a dead end on the first screen."""
    assert S.derive_session_name("!!!").startswith("wa-")


def test_a_posted_session_name_is_treated_as_a_label():
    """Older clients still post `session_name`. It must never be used verbatim
    as the key, or two tenants can collide and the insert 500s."""
    body = S.CreateSessionRequest(session_name="main-support-line")
    assert body.display_label == "main-support-line"


# --- W1: the status page's fields ----------------------------------------------- #
def test_session_response_carries_what_a_status_page_needs():
    fields = set(S.SessionResponse.model_fields)
    assert {"phone_number", "connected_at", "last_event_at", "status"} <= fields


@pytest.mark.asyncio
async def test_list_sessions_reports_last_event():
    """"Received messages two days ago" is the fact the page existed to show and
    did not. It is derived from conversations rather than a new column."""
    seen = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    row = _row()
    out = await S.list_sessions(tenant_id=row.tenant_id, db=_db(row, seen))
    assert out[0].last_event_at == seen
    assert out[0].connected_at == row.created_at


@pytest.mark.asyncio
async def test_status_returns_the_page_fields_and_adopts_the_number():
    row = _row()
    waha = AsyncMock()
    waha.get_session.return_value = {
        "status": "WORKING",
        "me": {"id": "923001234567@c.us", "pushName": "Salon"},
    }
    out = await S.session_status("front-desk-abcd1234", db=_db(row), waha=waha)
    assert out["status"] == "WORKING"
    assert out["phone_number"] == "923001234567"
    assert out["label"] == "Front desk"
    # Persisted, so the list endpoint can show it without a WAHA round-trip.
    assert row.phone_number == "923001234567"


def test_a_lid_is_never_shown_as_the_business_number():
    """Modern accounts message from `@lid`, an opaque linked id (CLAUDE.md).
    Printing its user part would put a plausible wrong number on the one page
    whose job is to say which number is live."""
    row = _row()
    S._adopt_phone_number(row, {"me": {"id": "112233445566@lid"}})
    assert row.phone_number is None


def test_status_survives_a_waha_response_with_no_me_block():
    """WAHA omits `me` until the session is WORKING."""
    row = _row(phone_number="923001234567")
    S._adopt_phone_number(row, {"status": "SCAN_QR_CODE"})
    assert row.phone_number == "923001234567"


# --- W1: recovery is on the owner API, not only the admin console --------------- #
@pytest.mark.parametrize(
    ("endpoint", "gate"),
    [(S.restart_session, require_owner), (S.logout_session, require_verified_owner)],
)
def test_recovery_routes_are_owner_gated(endpoint, gate):
    """Restart is recovery, so it is not held back by an unconfirmed address.
    Logout drops the link to the number and needs a fresh QR, so it is gated
    exactly like creating the session and fetching the QR."""
    gates = {
        param.default.dependency
        for param in inspect.signature(endpoint).parameters.values()
        if getattr(param.default, "dependency", None) is not None
    }
    assert gate in gates


@pytest.mark.asyncio
async def test_restart_stops_and_starts_through_waha():
    row = _row(status=SessionStatus.failed)
    waha = AsyncMock()
    waha.get_session.return_value = {"status": "SCAN_QR_CODE"}
    out = await S.restart_session(
        "front-desk-abcd1234",
        tenant_id=row.tenant_id,
        claims=None,
        db=_db(row),
        waha=waha,
    )
    waha.restart_session.assert_awaited_once_with("front-desk-abcd1234")
    # Read back rather than assumed: a restart lands in STARTING, STOPPED or
    # SCAN_QR_CODE depending on how the session dropped, and a guess would put a
    # state on the page that the next poll contradicts five seconds later.
    assert out["status"] == "SCAN_QR_CODE"


@pytest.mark.asyncio
async def test_restart_still_succeeds_when_the_status_read_back_fails():
    """The restart worked. A failed follow-up read must not turn it into a 502
    the owner reads as "recovery is broken"."""
    row = _row(status=SessionStatus.failed)
    waha = AsyncMock()
    waha.get_session.side_effect = WahaError(500, "boom")
    out = await S.restart_session(
        "front-desk-abcd1234",
        tenant_id=row.tenant_id,
        claims=None,
        db=_db(row),
        waha=waha,
    )
    assert out["status"] == SessionStatus.starting.value


@pytest.mark.asyncio
async def test_logout_clears_the_stored_number():
    """The number is no longer linked, so continuing to display it would be the
    page lying about the one thing it is for."""
    row = _row(phone_number="923001234567")
    waha = AsyncMock()
    waha.get_session.return_value = {"status": "STOPPED"}
    await S.logout_session(
        "front-desk-abcd1234",
        tenant_id=row.tenant_id,
        claims=None,
        db=_db(row),
        waha=waha,
    )
    waha.logout_session.assert_awaited_once_with("front-desk-abcd1234")
    assert row.phone_number is None
