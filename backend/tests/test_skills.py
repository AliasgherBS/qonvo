"""Skill handlers + idempotent execution ledger (DESIGN.md §5.3, §5.5, §7)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.enums import ConversationState, NotificationType
from app.skills.registry import (
    SKILL_REGISTRY,
    SkillContext,
    UnknownSkillError,
    enabled_tools,
    execute_skill,
)


def _ctx(db, **overrides) -> SkillContext:
    defaults = {
        "db": db,
        "tenant_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "idempotency_key": f"{uuid.uuid4()}:call_1",
    }
    defaults.update(overrides)
    return SkillContext(**defaults)


def _db_with_capture(db_add_target: list) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: db_add_target.append(obj))
    return db


# --- capture_lead --------------------------------------------------------------- #
async def test_capture_lead_requires_phone():
    db = AsyncMock()
    ctx = _ctx(db)
    result = await SKILL_REGISTRY["capture_lead"].handler(ctx, {"name": "Ali"})
    assert result["status"] == "error"


async def test_capture_lead_inserts_lead_row():
    added: list = []
    db = _db_with_capture(added)
    ctx = _ctx(db)

    result = await SKILL_REGISTRY["capture_lead"].handler(
        ctx, {"name": "Ali", "phone": "+92300", "intent": "wants a demo"}
    )

    assert result["status"] == "captured"
    assert len(added) == 1
    lead = added[0]
    assert lead.tenant_id == ctx.tenant_id
    assert lead.conversation_id == ctx.conversation_id
    assert lead.phone == "+92300"
    assert lead.name == "Ali"
    assert lead.notes == "wants a demo"
    db.flush.assert_awaited_once()


def test_capture_lead_tool_schema_requires_phone():
    schema = SKILL_REGISTRY["capture_lead"].tool_schema()
    assert schema["function"]["name"] == "capture_lead"
    assert "phone" in schema["function"]["parameters"]["required"]


# --- human_handoff --------------------------------------------------------------- #
async def test_human_handoff_sets_conversation_state_and_notifies():
    added: list = []
    db = _db_with_capture(added)

    class _FakeConversation:
        state = ConversationState.bot_active

    conversation = _FakeConversation()

    class _FakeTenantConfig:
        owner_alert_number = "923001234567"

    send_gateway = AsyncMock()
    ctx = _ctx(
        db,
        conversation=conversation,
        tenant_config=_FakeTenantConfig(),
        send_gateway=send_gateway,
        session_name="s1",
        chat_id="1@c.us",
    )

    result = await SKILL_REGISTRY["human_handoff"].handler(ctx, {"reason": "asked for manager"})

    assert result == {"status": "escalated", "message": "team notified"}
    assert conversation.state == ConversationState.needs_human
    handoffs = [o for o in added if type(o).__name__ == "Handoff"]
    notifications = [o for o in added if type(o).__name__ == "Notification"]
    assert len(handoffs) == 1
    assert handoffs[0].reason == "asked for manager"
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.escalation
    send_gateway.send_text.assert_awaited_once()
    call_args = send_gateway.send_text.await_args.args
    assert call_args[0] == "s1"
    assert call_args[1] == "923001234567@c.us"


async def test_human_handoff_skips_alert_without_owner_number():
    added: list = []
    db = _db_with_capture(added)

    class _FakeConversation:
        state = ConversationState.bot_active

    send_gateway = AsyncMock()
    ctx = _ctx(
        db,
        conversation=_FakeConversation(),
        tenant_config=None,
        send_gateway=send_gateway,
        session_name="s1",
        chat_id="1@c.us",
    )
    result = await SKILL_REGISTRY["human_handoff"].handler(ctx, {"reason": "unclear question"})
    assert result["status"] == "escalated"
    send_gateway.send_text.assert_not_awaited()


async def test_human_handoff_alert_failure_does_not_raise():
    added: list = []
    db = _db_with_capture(added)

    class _FakeConversation:
        state = ConversationState.bot_active

    class _FakeTenantConfig:
        owner_alert_number = "923001234567"

    send_gateway = AsyncMock()
    send_gateway.send_text.side_effect = RuntimeError("network down")
    ctx = _ctx(
        db,
        conversation=_FakeConversation(),
        tenant_config=_FakeTenantConfig(),
        send_gateway=send_gateway,
        session_name="s1",
        chat_id="1@c.us",
    )
    result = await SKILL_REGISTRY["human_handoff"].handler(ctx, {"reason": "x"})
    assert result["status"] == "escalated"  # alert failure must not break the handoff


# --- book_appointment ----------------------------------------------------------- #
class _FakeCalendar:
    def __init__(self) -> None:
        self.calls: list = []

    async def create_event(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "id": "evt_1",
            "html_link": "https://cal/evt_1",
            "start": kwargs["start"].isoformat(),
        }

    async def ping(self) -> None:  # pragma: no cover - unused here
        pass


async def test_book_appointment_creates_event_and_booking():
    added: list = []
    db = _db_with_capture(added)
    cal = _FakeCalendar()
    ctx = _ctx(
        db,
        chat_id="923001234567@c.us",
        integration_clients={"google_calendar": cal},
    )

    result = await SKILL_REGISTRY["book_appointment"].handler(
        ctx,
        {"summary": "Haircut", "start_time": "2026-07-12T15:00:00+05:00", "duration_minutes": 45},
    )

    assert result["status"] == "booked"
    assert result["event_id"] == "evt_1"
    assert len(cal.calls) == 1
    # duration_minutes drives the end time (15:00 + 45m = 15:45).
    call = cal.calls[0]
    assert (call["end"] - call["start"]).total_seconds() == 45 * 60
    bookings = [o for o in added if type(o).__name__ == "Booking"]
    assert len(bookings) == 1
    assert bookings[0].external_event_id == "evt_1"
    assert bookings[0].customer_phone == "923001234567"  # defaulted from chat_id
    db.flush.assert_awaited()


async def test_book_appointment_without_calendar_returns_error():
    db = AsyncMock()
    ctx = _ctx(db)  # no integration_clients, resolver will find no DB row either
    ctx.integration_clients = {}
    # Force resolver to see no client by injecting an empty dict AND stubbing DB build.
    from app.integrations import resolver

    async def _no_client(*_a, **_k):
        return None

    orig = resolver.build_calendar_client
    resolver.build_calendar_client = _no_client
    try:
        result = await SKILL_REGISTRY["book_appointment"].handler(
            ctx, {"summary": "x", "start_time": "2026-07-12T15:00:00+05:00"}
        )
    finally:
        resolver.build_calendar_client = orig
    assert result["status"] == "error"


async def test_book_appointment_rejects_bad_start_time():
    db = _db_with_capture([])
    ctx = _ctx(db, integration_clients={"google_calendar": _FakeCalendar()})
    result = await SKILL_REGISTRY["book_appointment"].handler(
        ctx, {"summary": "x", "start_time": "not-a-date"}
    )
    assert result["status"] == "error"


# --- append_to_sheet ------------------------------------------------------------- #
class _FakeSheet:
    def __init__(self) -> None:
        self.rows: list = []

    async def append_row(self, values: list) -> dict:
        self.rows.append(values)
        return {"updated_range": "Sheet1!A1:C1", "updated_rows": 1}

    async def ping(self) -> None:  # pragma: no cover
        pass


async def test_append_to_sheet_appends_field_values():
    db = AsyncMock()
    sheet = _FakeSheet()
    ctx = _ctx(db, integration_clients={"google_sheets": sheet})

    result = await SKILL_REGISTRY["append_to_sheet"].handler(
        ctx, {"fields": {"name": "Ali", "phone": "+92300", "request": "demo"}}
    )

    assert result["status"] == "recorded"
    assert sheet.rows == [["Ali", "+92300", "demo"]]


async def test_append_to_sheet_requires_fields():
    db = AsyncMock()
    ctx = _ctx(db, integration_clients={"google_sheets": _FakeSheet()})
    result = await SKILL_REGISTRY["append_to_sheet"].handler(ctx, {"fields": {}})
    assert result["status"] == "error"


# --- registry: enabled_tools + idempotent execution ------------------------------- #
async def test_execute_skill_unknown_name_raises():
    db = AsyncMock()
    with pytest.raises(UnknownSkillError):
        await execute_skill(_ctx(db), "not_a_real_skill", {})


async def test_execute_skill_runs_handler_once_and_caches_second_call():
    added: list = []
    db = _db_with_capture(added)
    db.execute = AsyncMock()
    # First lookup: no prior execution. Handler runs, we record its result.
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_result

    ctx = _ctx(db)
    result1 = await execute_skill(ctx, "capture_lead", {"phone": "+123"})
    assert result1["status"] == "captured"
    # A SkillExecution row was staged for idempotency.
    executions = [o for o in added if type(o).__name__ == "SkillExecution"]
    assert len(executions) == 1
    assert executions[0].idempotency_key == ctx.idempotency_key

    # Second call with the same idempotency key: pretend the ledger now has a row.
    cached_execution = MagicMock()
    cached_execution.result = {"status": "captured", "lead_id": "cached", "message": "cached"}
    scalar_result2 = MagicMock()
    scalar_result2.scalar_one_or_none.return_value = cached_execution
    db.execute.return_value = scalar_result2

    result2 = await execute_skill(ctx, "capture_lead", {"phone": "+123"})
    assert result2 == cached_execution.result
    # No second Lead/SkillExecution was added on the cached path.
    assert len([o for o in added if type(o).__name__ == "SkillExecution"]) == 1


def _skills_then_integrations(db, *, skill_rows, integration_rows):
    """Wire the two DB reads enabled_skill_names now makes (skills, then integrations)."""
    skills_result = MagicMock()
    skills_result.all.return_value = skill_rows
    integ_result = MagicMock()
    integ_result.scalars.return_value.all.return_value = integration_rows
    db.execute = AsyncMock(side_effect=[skills_result, integ_result])


async def test_enabled_tools_defaults_to_enabled_for_unconfigured_skills():
    db = AsyncMock()
    # No explicit skills rows and no integrations connected → integration-gated
    # skills (book_appointment, append_to_sheet) are hidden.
    _skills_then_integrations(db, skill_rows=[], integration_rows=[])

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert names == {"capture_lead", "human_handoff"}


async def test_enabled_tools_respects_explicit_disable():
    db = AsyncMock()
    _skills_then_integrations(db, skill_rows=[("human_handoff", False)], integration_rows=[])

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert names == {"capture_lead"}


async def test_enabled_tools_includes_google_skills_when_integrations_ready():
    db = AsyncMock()

    class _Integ:
        def __init__(self, provider, config):
            self.provider = provider
            self.config = config
            self.encrypted_credentials = "cipher"  # a per-tenant key is present

    _skills_then_integrations(
        db,
        skill_rows=[],
        integration_rows=[
            _Integ("google_calendar", {"calendar_id": "cal@group.calendar.google.com"}),
            _Integ("google_sheets", {"spreadsheet_id": "sheet123"}),
        ],
    )

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert names == {"capture_lead", "human_handoff", "book_appointment", "append_to_sheet"}


async def test_enabled_tools_hides_google_skill_when_target_id_missing():
    db = AsyncMock()

    class _Integ:
        provider = "google_calendar"
        config: dict = {}  # enabled + key but no calendar_id → not ready
        encrypted_credentials = "cipher"

    _skills_then_integrations(db, skill_rows=[], integration_rows=[_Integ()])

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert "book_appointment" not in names
