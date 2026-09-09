"""Proof an integration has been used, not just connected (teardown N3).

The cards said "Connected", which means the token works. It does not mean the
rep has booked anything or written a row, and the owner's real question was
answerable only by opening Google.

Nothing here invents a number. Bookings are rows in ``bookings``; sheet appends
have no table of their own but every write-skill call is already recorded in the
``skill_executions`` idempotency ledger (§7), which is what the count reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api import integrations as I
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from sqlalchemy.dialects import postgresql

_MONTH_START = datetime(2026, 9, 1, tzinfo=UTC)


def _db(last_at, month_count) -> AsyncMock:
    result = MagicMock()
    result.one.return_value = (last_at, month_count)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_calendar_usage_counts_bookings():
    last = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    usage = await I._usage(_db(last, 14), uuid.uuid4(), GOOGLE_CALENDAR, _MONTH_START)
    assert usage is not None
    assert usage.last_at == last.isoformat()
    assert usage.month_count == 14
    # The dashboard renders "Last booking 2 hours ago" from this rather than
    # keeping its own provider -> wording map.
    assert usage.unit == "booking"


@pytest.mark.asyncio
async def test_sheets_usage_counts_rows():
    usage = await I._usage(_db(None, 0), uuid.uuid4(), GOOGLE_SHEETS, _MONTH_START)
    assert usage is not None
    assert usage.unit == "row"
    # Never used reads as never used, not as a zero dressed up as a metric.
    assert usage.last_at is None
    assert usage.month_count == 0


@pytest.mark.asyncio
async def test_a_provider_with_nothing_recorded_reports_no_usage():
    """A line has to be backed by a record. A provider whose use is not
    recorded anywhere gets no line rather than a fabricated one."""
    assert await I._usage(_db(None, 0), uuid.uuid4(), "someday_crm", _MONTH_START) is None


@pytest.mark.asyncio
async def test_failed_sheet_appends_are_not_counted_as_rows_written():
    """The ledger records refusals too ("the spreadsheet isn't connected yet").
    Counting those as rows written would be the exact lie the line exists to
    stop telling."""
    db = _db(None, 0)
    await I._usage(db, uuid.uuid4(), GOOGLE_SHEETS, _MONTH_START)
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "skill_executions.result ->>" in sql
    assert "skill_executions.skill_key" in sql


@pytest.mark.asyncio
async def test_unconnected_providers_get_no_usage_and_cost_no_queries():
    """A "0 this month" line on a card nobody has connected reads as a failure
    rather than as an absence -- and the month boundary needs the tenant's
    timezone, which is a query worth skipping when there is nothing to count."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=AssertionError("should not query"))
    monkeypatched = AsyncMock(return_value=[])
    original = I.svc.list_integrations
    I.svc.list_integrations = monkeypatched  # type: ignore[assignment]
    try:
        out = await I.list_integrations(tenant_id=uuid.uuid4(), db=db)
    finally:
        I.svc.list_integrations = original  # type: ignore[assignment]
    assert out and all(row.usage is None for row in out)
