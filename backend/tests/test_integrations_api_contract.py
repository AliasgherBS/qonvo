"""What the /api/integrations routes promise, and what a failed Test says.

Written after a live report of "multiple errors" on the Sheets card that the
server-side record could not explain. Two classes of thing are pinned here.

**The response contract.** Several routes build ``IntegrationResponse`` from
``svc.sanitized(integration)`` alone, while ``GET /api/integrations`` also
passes ``usage=``. A field added to that model without a default therefore
would not fail a review or a type check -- it would 500 the PUT, the calendar
provision and the OAuth callback the next time an owner touched them, while the
list endpoint that the new field was written for kept working. That asymmetry
is invisible in a diff, so it is asserted instead.

**The failed-test message.** ``str(HttpError)`` is a request dump: it names the
API endpoint, embeds the spreadsheet id and ends in a Google phrase that tells
an owner nothing to do. The two statuses that have a single owner-actionable
cause say what it is.

Hermetic: no Google client is built and no network is touched.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api import integrations as I
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS, SUPPORTED_PROVIDERS
from app.integrations.resolver import STATE_OK
from app.models.skill import Integration
from app.services import integrations as svc

_TENANT = uuid.uuid4()


class _FakeResp:
    """Stands in for ``httplib2.Response`` on a googleapiclient ``HttpError``."""

    def __init__(self, status: int) -> None:
        self.status = status


class _FakeHttpError(Exception):
    """Shaped like ``googleapiclient.errors.HttpError`` without importing it.

    The real class is only reachable once the heavy Google client is installed,
    and the code under test deliberately duck-types the status for exactly that
    reason -- so the test duck-types it back.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.resp = _FakeResp(status)
        self._message = message

    def __str__(self) -> str:  # what the owner used to be shown verbatim
        return self._message


def _connected(provider: str) -> Integration:
    integration = Integration(tenant_id=_TENANT, provider=provider, config={})
    integration.enabled = True
    integration.config = {
        "account_email": "owner@example.test",
        "granted_scopes": ["s"],
        "connected_at": "2026-09-05T18:26:11+00:00",
        **(
            {"spreadsheet_id": "sheet-1", "spreadsheet_title": "Leads"}
            if provider == GOOGLE_SHEETS
            else {"calendar_id": "cal-1", "calendar_summary": "Qonvo Bookings"}
        ),
    }
    return integration


# --- the response contract ------------------------------------------------------- #
@pytest.mark.parametrize("provider", sorted(SUPPORTED_PROVIDERS))
def test_sanitized_alone_builds_a_valid_integration_response(provider):
    """The shape PUT, provision and the OAuth callback all return.

    They pass no ``usage``. If anything added to ``IntegrationResponse`` stops
    being optional, this is the call that 500s -- and it 500s on the owner's
    settings save, not on the endpoint the new field was added for.
    """
    response = I.IntegrationResponse(**svc.sanitized(_connected(provider)))
    assert response.provider == provider
    assert response.usage is None


@pytest.mark.parametrize("provider", sorted(SUPPORTED_PROVIDERS))
def test_unconnected_stub_builds_a_valid_integration_response(provider):
    """The stub row the list endpoint emits for a provider nobody has connected."""
    assert I.IntegrationResponse(**svc.unconnected(provider)).connected is False


def test_usage_is_optional_on_the_response_model():
    """Stated directly, so the reason the field has a default is not lost.

    A never-connected provider gets no usage line at all: "0 this month" on an
    empty card reads as failure rather than as absence.
    """
    assert I.IntegrationResponse.model_fields["usage"].is_required() is False


def test_sheet_target_response_needs_every_field_the_select_route_sends():
    """The Picker's round trip. ``tabs`` may legitimately be empty, never absent."""
    target = I.SheetTargetResponse(
        spreadsheet_id="sheet-1", title="Leads", tabs=[], sheet_range="Sheet1"
    )
    assert target.sheet_range == "Sheet1"


# --- a failed Test connection ---------------------------------------------------- #
def _test_route_env(monkeypatch, provider: str, integration: Integration, client):
    monkeypatch.setattr(I.svc, "get_integration", AsyncMock(return_value=integration))
    monkeypatch.setattr(I, "credential_state", lambda _i: STATE_OK)
    builder = AsyncMock(return_value=client)
    monkeypatch.setattr(
        I, "build_sheets_client" if provider == GOOGLE_SHEETS else "build_calendar_client", builder
    )


def _client_that_fails(exc: BaseException) -> MagicMock:
    client = MagicMock()
    client.ping = AsyncMock(side_effect=exc)
    return client


@pytest.mark.asyncio
async def test_sheets_404_tells_the_owner_to_pick_the_sheet_again(monkeypatch):
    """Under ``drive.file`` this is the only thing that helps, and Reconnect is not it.

    A stored spreadsheet id that has stopped resolving means the Picker
    selection no longer grants access. Google's own text for it is "Requested
    entity was not found.", which sends an owner to the reconnect button, where
    a fresh grant still will not reach a file nobody has re-picked.
    """
    exc = _FakeHttpError(404, "Requested entity was not found.")
    _test_route_env(monkeypatch, GOOGLE_SHEETS, _connected(GOOGLE_SHEETS), _client_that_fails(exc))

    result = await I.test_integration(GOOGLE_SHEETS, tenant_id=_TENANT, db=AsyncMock())

    assert result.ok is False
    assert "pick it again" in result.message
    # And the id is not echoed into the toast along the way.
    assert "sheet-1" not in result.message


@pytest.mark.asyncio
async def test_sheets_403_is_the_same_lost_access(monkeypatch):
    exc = _FakeHttpError(403, "The caller does not have permission")
    _test_route_env(monkeypatch, GOOGLE_SHEETS, _connected(GOOGLE_SHEETS), _client_that_fails(exc))

    result = await I.test_integration(GOOGLE_SHEETS, tenant_id=_TENANT, db=AsyncMock())

    assert result.ok is False
    assert "pick it again" in result.message


@pytest.mark.asyncio
async def test_calendar_404_points_at_reconnecting_not_at_the_sheet_chooser(monkeypatch):
    exc = _FakeHttpError(404, "Not Found")
    integration = _connected(GOOGLE_CALENDAR)
    _test_route_env(monkeypatch, GOOGLE_CALENDAR, integration, _client_that_fails(exc))

    result = await I.test_integration(GOOGLE_CALENDAR, tenant_id=_TENANT, db=AsyncMock())

    assert result.ok is False
    assert "create it again" in result.message


@pytest.mark.asyncio
async def test_an_unrecognised_failure_keeps_googles_own_words(monkeypatch):
    """A guess is worse than Google's text when we do not know the cause."""
    exc = _FakeHttpError(500, "Internal error encountered.")
    _test_route_env(monkeypatch, GOOGLE_SHEETS, _connected(GOOGLE_SHEETS), _client_that_fails(exc))

    result = await I.test_integration(GOOGLE_SHEETS, tenant_id=_TENANT, db=AsyncMock())

    assert result.message == "Internal error encountered."


@pytest.mark.asyncio
async def test_a_failed_ping_is_logged(monkeypatch, caplog):
    """The reason this test file exists.

    This branch is the only one in the route that reaches Google, and it used
    to record nothing: a live failure left the message in one owner's browser
    and no trace on the server, so the report could not be answered afterwards.
    """
    from app.core.logging import logger

    records: list[str] = []
    sink_id = logger.add(lambda m: records.append(m.record["message"]), level="WARNING")
    try:
        exc = _FakeHttpError(404, "Requested entity was not found.")
        _test_route_env(
            monkeypatch, GOOGLE_SHEETS, _connected(GOOGLE_SHEETS), _client_that_fails(exc)
        )
        await I.test_integration(GOOGLE_SHEETS, tenant_id=_TENANT, db=AsyncMock())
    finally:
        logger.remove(sink_id)

    assert any(GOOGLE_SHEETS in line and "not found" in line for line in records)


@pytest.mark.asyncio
async def test_no_target_is_reported_as_almost_there_not_as_an_error(monkeypatch):
    """A builder returning None means "nothing chosen yet", which is not a fault."""
    _test_route_env(monkeypatch, GOOGLE_SHEETS, _connected(GOOGLE_SHEETS), None)

    result = await I.test_integration(GOOGLE_SHEETS, tenant_id=_TENANT, db=AsyncMock())

    assert result.ok is False
    assert "no spreadsheet has been chosen yet" in result.message


@pytest.mark.asyncio
async def test_a_working_connection_names_the_account(monkeypatch):
    client = MagicMock()
    client.ping = AsyncMock(return_value=None)
    _test_route_env(monkeypatch, GOOGLE_SHEETS, _connected(GOOGLE_SHEETS), client)

    result = await I.test_integration(GOOGLE_SHEETS, tenant_id=_TENANT, db=AsyncMock())

    assert result.ok is True
    assert result.account_email == "owner@example.test"
