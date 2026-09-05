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
    # A bare AsyncMock returns a truthy MagicMock from every lookup, which reads
    # as "a row already exists" to any skill that checks. Default every query to
    # "found nothing"; tests that need a hit override it.
    empty = MagicMock()
    empty.scalar_one_or_none = MagicMock(return_value=None)
    empty.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(return_value=empty)
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

    # The reason comes back so the pipeline can record it against the question
    # that triggered it, which is what the owner's escalation report joins on.
    assert result == {
        "status": "escalated",
        "message": "team notified",
        "reason": "asked for manager",
    }
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


async def test_human_handoff_respects_notify_off_but_still_records():
    added: list = []
    db = _db_with_capture(added)

    class _FakeConversation:
        state = ConversationState.bot_active

    class _MutedConfig:
        owner_alert_number = "923001234567"
        escalation_rules = {"notify_on_handoff": False}

    send_gateway = AsyncMock()
    ctx = _ctx(
        db,
        conversation=_FakeConversation(),
        tenant_config=_MutedConfig(),
        send_gateway=send_gateway,
        session_name="s1",
        chat_id="1@c.us",
    )
    result = await SKILL_REGISTRY["human_handoff"].handler(ctx, {"reason": "asked for manager"})
    assert result["status"] == "escalated"
    # Push alert muted...
    send_gateway.send_text.assert_not_awaited()
    # ...but the in-app Notification + Handoff record are still written.
    assert any(type(o).__name__ == "Notification" for o in added)
    assert any(type(o).__name__ == "Handoff" for o in added)


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


# Skills with no integration/config requirement → on by default.
_BASE_SKILLS = {"capture_lead", "human_handoff", "take_order"}


def _skills_then_integrations(db, *, skill_rows, integration_rows, tenant_config=None):
    """Wire the three DB reads enabled_skill_names makes: skills, integrations, config."""
    skills_result = MagicMock()
    skills_result.all.return_value = skill_rows
    integ_result = MagicMock()
    integ_result.scalars.return_value.all.return_value = integration_rows
    config_result = MagicMock()
    config_result.scalar_one_or_none.return_value = tenant_config
    db.execute = AsyncMock(side_effect=[skills_result, integ_result, config_result])


async def test_enabled_tools_defaults_to_enabled_for_unconfigured_skills():
    db = AsyncMock()
    # No integrations + no payment config → integration- and config-gated skills
    # are hidden; only the always-on base skills remain.
    _skills_then_integrations(db, skill_rows=[], integration_rows=[])

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert names == _BASE_SKILLS


async def test_enabled_tools_respects_explicit_disable():
    db = AsyncMock()
    _skills_then_integrations(db, skill_rows=[("human_handoff", False)], integration_rows=[])

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert names == _BASE_SKILLS - {"human_handoff"}


def _granted(provider: str, **config) -> object:
    """An integration row holding a live OAuth grant for ``provider``."""
    import json as _json

    from app.core.security import encrypt_secret
    from app.integrations.scopes import CALENDAR_SCOPE, SHEETS_SCOPE

    scope = CALENDAR_SCOPE if provider == "google_calendar" else SHEETS_SCOPE

    class _Integ:
        pass

    integ = _Integ()
    integ.provider = provider
    integ.config = {"granted_scopes": [scope], **config}
    integ.encrypted_credentials = encrypt_secret(_json.dumps({"refresh_token": "1//rt"}))
    return integ


async def test_enabled_tools_includes_google_skills_when_integrations_ready():
    db = AsyncMock()
    _skills_then_integrations(
        db,
        skill_rows=[],
        integration_rows=[
            _granted("google_calendar", calendar_id="cal@group.calendar.google.com"),
            _granted("google_sheets", spreadsheet_id="sheet123"),
        ],
    )

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert names == _BASE_SKILLS | {
        "book_appointment",
        "append_to_sheet",
        "check_availability",
        "lookup_sheet",
    }


async def test_enabled_tools_hides_google_skill_when_target_id_missing():
    db = AsyncMock()
    # Live grant but nothing provisioned yet → not ready.
    _skills_then_integrations(db, skill_rows=[], integration_rows=[_granted("google_calendar")])

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert "book_appointment" not in names
    assert "check_availability" not in names


async def test_enabled_tools_drops_google_skills_when_grant_needs_reauth():
    """The revocation degradation path, end to end: once a grant dies the model
    must stop being offered booking tools on the very next turn, rather than
    calling them and failing in front of a customer."""
    db = AsyncMock()
    _skills_then_integrations(
        db,
        skill_rows=[],
        integration_rows=[
            _granted("google_calendar", calendar_id="cal123", needs_reauth=True),
            _granted("google_sheets", spreadsheet_id="sheet123"),
        ],
    )

    tools = await enabled_tools(db, uuid.uuid4())
    names = {t["function"]["name"] for t in tools}
    assert "book_appointment" not in names
    assert "check_availability" not in names
    # The healthy provider is untouched — one dead grant must not disable the other.
    assert "append_to_sheet" in names
    assert "lookup_sheet" in names


async def test_enabled_tools_shows_payment_skill_only_when_configured():
    class _Config:
        payment_details = "Bank: HBL, Acct: 1234"

    db = AsyncMock()
    _skills_then_integrations(db, skill_rows=[], integration_rows=[], tenant_config=_Config())
    names = {t["function"]["name"] for t in await enabled_tools(db, uuid.uuid4())}
    assert "share_payment_details" in names

    db2 = AsyncMock()
    _skills_then_integrations(db2, skill_rows=[], integration_rows=[], tenant_config=None)
    names2 = {t["function"]["name"] for t in await enabled_tools(db2, uuid.uuid4())}
    assert "share_payment_details" not in names2


# --- new Phase 3 skills: lookup / availability / order / payment ------------------ #
async def test_take_order_records_order_and_total():
    added: list = []
    db = _db_with_capture(added)
    ctx = _ctx(db, chat_id="923009999999@c.us")
    result = await SKILL_REGISTRY["take_order"].handler(
        ctx,
        {"items": [{"name": "Keratin", "quantity": 2, "price": 12000}], "customer_name": "Sara"},
    )
    assert result["status"] == "ordered"
    assert result["total"] == 24000
    orders = [o for o in added if type(o).__name__ == "Order"]
    assert len(orders) == 1
    assert orders[0].customer_phone == "923009999999"
    assert orders[0].total == 24000


async def test_take_order_requires_items():
    db = _db_with_capture([])
    result = await SKILL_REGISTRY["take_order"].handler(_ctx(db), {"items": []})
    assert result["status"] == "error"


async def test_take_order_total_none_when_price_missing():
    added: list = []
    db = _db_with_capture(added)
    result = await SKILL_REGISTRY["take_order"].handler(
        _ctx(db), {"items": [{"name": "Haircut", "quantity": 1}]}
    )
    assert result["total"] is None


class _FakeSheetReader:
    def __init__(self, rows):
        self._rows = rows

    async def read_rows(self):
        return self._rows


async def test_lookup_sheet_returns_matching_rows():
    sheet = _FakeSheetReader(
        [["Item", "Price", "Stock"], ["Shampoo", "500", "12"], ["Keratin", "12000", "3"]]
    )
    ctx = _ctx(AsyncMock(), integration_clients={"google_sheets": sheet})
    result = await SKILL_REGISTRY["lookup_sheet"].handler(ctx, {"query": "keratin"})
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["matches"][0]["Item"] == "Keratin"
    assert result["matches"][0]["Price"] == "12000"


async def test_lookup_sheet_no_match():
    sheet = _FakeSheetReader([["Item"], ["Shampoo"]])
    ctx = _ctx(AsyncMock(), integration_clients={"google_sheets": sheet})
    result = await SKILL_REGISTRY["lookup_sheet"].handler(ctx, {"query": "nonexistent"})
    assert result["count"] == 0


class _FakeCalendarReader:
    def __init__(self, events):
        self._events = events

    async def list_events(self, *, time_min, time_max):
        return self._events


async def test_check_availability_reports_busy():
    cal = _FakeCalendarReader(
        [
            {
                "summary": "Bridal",
                "start": "2026-07-20T10:00:00+05:00",
                "end": "2026-07-20T12:00:00+05:00",
            }
        ]
    )
    ctx = _ctx(AsyncMock(), integration_clients={"google_calendar": cal})
    result = await SKILL_REGISTRY["check_availability"].handler(ctx, {"date": "2026-07-20"})
    assert result["status"] == "ok"
    assert len(result["busy"]) == 1


async def test_check_availability_rejects_bad_date():
    cal = _FakeCalendarReader([])
    ctx = _ctx(AsyncMock(), integration_clients={"google_calendar": cal})
    result = await SKILL_REGISTRY["check_availability"].handler(ctx, {"date": "not-a-date"})
    assert result["status"] == "error"


async def test_share_payment_details_returns_configured_details():
    class _Config:
        payment_details = "Bank: HBL\nTitle: Glow Salon\nAcct: 1234567890"

    ctx = _ctx(AsyncMock(), tenant_config=_Config())
    result = await SKILL_REGISTRY["share_payment_details"].handler(ctx, {})
    assert result["status"] == "ok"
    assert "HBL" in result["payment_details"]


async def test_share_payment_details_errors_when_unset():
    class _Config:
        payment_details = None

    ctx = _ctx(AsyncMock(), tenant_config=_Config())
    result = await SKILL_REGISTRY["share_payment_details"].handler(ctx, {})
    assert result["status"] == "error"


# --- escalating the same issue twice ------------------------------------------ #
def _db_with_open_handoff(added: list, open_handoff) -> AsyncMock:
    """Capture db.add, and answer the "is one already open?" lookup."""
    db = _db_with_capture(added)
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=open_handoff)
    db.execute = AsyncMock(return_value=result)
    return db


async def test_handoff_does_not_re_escalate_an_already_open_issue():
    """The bot keeps talking after an escalation now, so it will meet the topic
    again. Re-escalating would alert the owner twice for one problem and pile up
    open rows nobody closes."""
    added: list = []

    class _FakeConversation:
        state = ConversationState.bot_active

    db = _db_with_open_handoff(added, open_handoff=MagicMock(reason="Refund for a colour."))
    ctx = _ctx(db, conversation=_FakeConversation())

    result = await SKILL_REGISTRY["human_handoff"].handler(
        ctx, {"reason": "still asking about the refund"}
    )

    assert result["status"] == "already_escalated"
    assert added == [], "a second handoff row or notification was created"


async def test_handoff_escalates_when_nothing_is_open():
    added: list = []

    class _FakeConversation:
        state = ConversationState.bot_active

    conversation = _FakeConversation()
    db = _db_with_open_handoff(added, open_handoff=None)
    ctx = _ctx(db, conversation=conversation)

    result = await SKILL_REGISTRY["human_handoff"].handler(ctx, {"reason": "a new problem"})

    assert result["status"] == "escalated"
    assert len(added) == 2, "expected one Handoff and one Notification"
    assert conversation.state == ConversationState.needs_human
