"""Pipeline gates, grounding prompt, tool loop, and cost (DESIGN.md §5.4, §13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from app.core.logging import logger
from app.models.enums import ConversationState
from app.providers.base import ChatMessage, LLMResult, ToolCall
from app.waha.send_gateway import SessionPacing
from app.workers import pipeline
from app.workers.pipeline import (
    build_system_prompt,
    build_turn_prompt,
    business_hours_closed_reply,
    compute_cost,
    is_hard_quota_exceeded,
    is_paused,
    is_within_business_hours,
    run_tool_loop,
    should_auto_resume,
    should_refresh_summary,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)  # a Thursday, noon UTC


# --- pause / takeover gate ----------------------------------------------------- #
def test_bot_active_never_paused():
    assert is_paused(ConversationState.bot_active, None, now=NOW) is False


@pytest.mark.parametrize(
    "state",
    [
        ConversationState.paused_by_agent,
        ConversationState.paused_by_owner,
        ConversationState.needs_human,
    ],
)
def test_paused_states_block_without_ttl(state):
    assert is_paused(state, None, now=NOW) is True


def test_auto_resume_after_ttl_elapsed():
    paused_until = NOW - timedelta(seconds=1)
    assert should_auto_resume(ConversationState.paused_by_owner, paused_until, now=NOW) is True
    assert is_paused(ConversationState.paused_by_owner, paused_until, now=NOW) is False


def test_still_paused_before_ttl():
    paused_until = NOW + timedelta(hours=1)
    assert should_auto_resume(ConversationState.paused_by_owner, paused_until, now=NOW) is False
    assert is_paused(ConversationState.paused_by_owner, paused_until, now=NOW) is True


# --- business hours gate -------------------------------------------------------- #
def test_business_hours_disabled_is_always_open():
    assert is_within_business_hours({}, now=NOW) is True
    assert is_within_business_hours({"enabled": False}, now=NOW) is True


def test_business_hours_open_within_window():
    hours = {
        "enabled": True,
        "timezone": "UTC",
        "hours": {"thu": [["09:00", "17:00"]]},
    }
    assert is_within_business_hours(hours, now=NOW) is True


def test_business_hours_closed_outside_window():
    hours = {
        "enabled": True,
        "timezone": "UTC",
        "hours": {"thu": [["09:00", "10:00"]]},
    }
    assert is_within_business_hours(hours, now=NOW) is False


def test_business_hours_closed_no_window_for_day():
    hours = {"enabled": True, "timezone": "UTC", "hours": {"mon": [["09:00", "17:00"]]}}
    assert is_within_business_hours(hours, now=NOW) is False


def test_business_hours_closed_reply_uses_configured_message():
    assert business_hours_closed_reply({"closed_message": "We're closed!"}) == "We're closed!"
    assert "closed" in business_hours_closed_reply({}).lower()


# --- quota gate ------------------------------------------------------------------ #
def test_quota_not_exceeded_when_unconfigured():
    assert is_hard_quota_exceeded({}, messages_this_period=100_000) is False


def test_quota_exceeded_at_threshold():
    assert is_hard_quota_exceeded({"monthly_message_quota": 100}, messages_this_period=100) is True
    assert is_hard_quota_exceeded({"monthly_message_quota": 100}, messages_this_period=99) is False


# --- grounding prompt assembly --------------------------------------------------- #
# The prompt is split in two so the system half can be served from a provider's
# automatic prompt cache: persona and rules are stable, knowledge and the
# question are not. See tests/test_prompt_caching.py for the ordering property.
def test_prompt_includes_grounding_instruction_and_business_name():
    prompt = build_system_prompt(
        business_name="Acme Cafe",
        persona="Friendly and upbeat.",
        tone="Warm",
        custom_instructions="Always mention our loyalty card.",
        primary_language="en",
    )
    assert "Acme Cafe" in prompt
    assert "Friendly and upbeat." in prompt
    assert "Warm" in prompt
    assert "loyalty card" in prompt
    assert "ONLY using the business knowledge" in prompt
    assert "human_handoff" in prompt
    assert "customer's language" in prompt


def test_retrieved_knowledge_reaches_the_model_in_the_turn():
    turn = build_turn_prompt(
        context_block="[1] We open at 9am.",
        conversation_summary=None,
        message="what time do you open?",
    )
    assert "[1] We open at 9am." in turn
    assert "what time do you open?" in turn


def test_prompt_notes_missing_knowledge_when_context_empty():
    turn = build_turn_prompt(context_block="", conversation_summary=None, message="hi")
    assert "No relevant business knowledge was found" in turn

    prompt = build_system_prompt(
        business_name=None,
        persona=None,
        tone=None,
        custom_instructions=None,
        primary_language="en",
    )
    assert "this business" in prompt


# --- summary refresh cadence ------------------------------------------------------ #
def test_should_refresh_summary_every_n_turns():
    assert should_refresh_summary(10, refresh_every=10) is True
    assert should_refresh_summary(9, refresh_every=10) is False
    assert should_refresh_summary(20, refresh_every=10) is True


# --- cost --------------------------------------------------------------------------- #
def test_compute_cost_from_pricing_table():
    pricing = {"openai": {"gpt-4o-mini": {"input": 0.001, "output": 0.002}}}
    cost = compute_cost("openai", "gpt-4o-mini", 1000, 500, pricing=pricing)
    assert cost == pytest.approx(0.001 + 0.001)


def test_compute_cost_unknown_model_is_zero():
    assert compute_cost("openai", "no-such-model", 1000, 1000, pricing={}) == 0.0


# --- tool loop with a mocked LLM calling capture_lead ------------------------------ #
@dataclass
class _ScriptedLLM:
    responses: list[LLMResult]
    calls: list = field(default_factory=list)

    async def generate(self, messages, *, tools=None, model=None):
        self.calls.append(list(messages))
        return self.responses.pop(0)


async def test_tool_loop_executes_capture_lead_then_returns_final_answer():
    tool_call = ToolCall(id="call_1", name="capture_lead", arguments={"phone": "+123"})
    llm = _ScriptedLLM(
        responses=[
            LLMResult(text="", tool_calls=[tool_call], prompt_tokens=10, completion_tokens=5),
            LLMResult(text="Thanks, we'll follow up!", prompt_tokens=20, completion_tokens=8),
        ]
    )
    dispatched: list[ToolCall] = []

    async def dispatch(call: ToolCall) -> dict:
        dispatched.append(call)
        return {"status": "captured", "message": "ok"}

    result = await run_tool_loop(
        llm,
        [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="call me")],
        tools=[{"type": "function", "function": {"name": "capture_lead"}}],
        dispatch=dispatch,
        max_iterations=5,
    )

    assert result.text == "Thanks, we'll follow up!"
    assert result.iterations == 2
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 13
    assert dispatched == [tool_call]
    assert result.tool_results == [{"status": "captured", "message": "ok"}]
    # The transcript carries the assistant tool-call message and the tool reply.
    roles = [m.role for m in result.transcript]
    assert roles == ["system", "user", "assistant", "tool"]


async def test_tool_loop_stops_at_max_iterations_without_final_answer():
    always_calls = ToolCall(id="call_x", name="capture_lead", arguments={})
    llm = _ScriptedLLM(
        responses=[
            LLMResult(text="", tool_calls=[always_calls]) for _ in range(3)
        ]
    )

    async def dispatch(call: ToolCall) -> dict:
        return {"status": "captured"}

    result = await run_tool_loop(
        llm,
        [ChatMessage(role="user", content="hi")],
        tools=None,
        dispatch=dispatch,
        max_iterations=3,
    )
    assert result.iterations == 3
    assert len(llm.calls) == 3


async def test_tool_loop_returns_immediately_with_no_tool_calls():
    llm = _ScriptedLLM(responses=[LLMResult(text="just an answer")])
    called = False

    async def dispatch(call: ToolCall) -> dict:
        nonlocal called
        called = True
        return {}

    result = await run_tool_loop(
        llm, [ChatMessage(role="user", content="hi")], tools=None, dispatch=dispatch
    )
    assert result.text == "just an answer"
    assert result.iterations == 1
    assert called is False


# --------------------------------------------------------------------------- #
# Send pacing (DESIGN.md §5.6)
# --------------------------------------------------------------------------- #
class _CapturingGateway:
    """Records the pacing each send was given."""

    def __init__(self) -> None:
        self.pacing: SessionPacing | None = None

    async def send_text(self, _session, _chat_id, _text, *, pacing):
        self.pacing = pacing
        return {}

    async def send_voice(self, _session, _chat_id, *, data, pacing):
        self.pacing = pacing
        return {}


@pytest.mark.asyncio
async def test_bot_text_reply_is_sent_with_the_session_pacing():
    """A bot reply must be paced by the session it is sent from, not by defaults."""
    gateway = _CapturingGateway()
    pacing = SessionPacing(daily_cap=40, warmup_stage=2)

    await pipeline._send(logger, gateway, "s1", "1@c.us", "hi", pacing)

    assert gateway.pacing == pacing


@pytest.mark.asyncio
async def test_bot_voice_reply_is_sent_with_the_session_pacing():
    """Voice replies count against the same cap as text ones."""
    gateway = _CapturingGateway()
    pacing = SessionPacing(daily_cap=40, warmup_stage=2)

    await pipeline._send_voice(logger, gateway, "s1", "1@c.us", "YWJj", pacing)

    assert gateway.pacing == pacing


# --- cached-token pricing ---------------------------------------------------- #
# Providers bill a cached prefix at roughly a tenth of the input rate. Measured
# on gpt-5-nano: 2,048 of 2,161 prompt tokens served from cache. Ignoring that
# over-reports cost by several times once caching is working.
_RATES = {"openai": {"m": {"input": 0.0002, "cached_input": 0.00002, "output": 0.00125}}}


def test_cost_bills_cached_tokens_at_the_cached_rate():
    full = compute_cost("openai", "m", 10_000, 1_000, pricing=_RATES)
    mostly_cached = compute_cost(
        "openai", "m", 10_000, 1_000, cached_tokens=9_000, pricing=_RATES
    )

    # 1k fresh + 9k cached + 1k output, versus 10k fresh + 1k output.
    assert mostly_cached < full
    assert mostly_cached == pytest.approx(
        (1_000 / 1000) * 0.0002 + (9_000 / 1000) * 0.00002 + (1_000 / 1000) * 0.00125
    )


def test_cost_without_a_cached_rate_falls_back_to_the_input_rate():
    """A model whose cached rate we have not recorded must not be billed at
    zero for its cached half -- silently under-reporting is worse than a
    slightly high number."""
    rates = {"openai": {"m": {"input": 0.0002, "output": 0.00125}}}

    assert compute_cost("openai", "m", 10_000, 0, cached_tokens=9_000, pricing=rates) == (
        pytest.approx((10_000 / 1000) * 0.0002)
    )


def test_cached_tokens_cannot_exceed_the_prompt():
    """Defensive: a provider reporting nonsense must not produce a negative bill."""
    cost = compute_cost("openai", "m", 100, 0, cached_tokens=9_999, pricing=_RATES)

    assert cost >= 0


# --- every billed call must be recorded --------------------------------------- #
# The chat completion was the only call feeding usage_counters. Four others are
# billed and were invisible: the summary refresh, the per-query embedding, the
# ingestion embeddings, and voice. The first two are token-priced and covered
# here; voice needs its own per-character/per-second rates.
async def test_summary_refresh_reports_what_it_cost():
    """It sends the whole windowed transcript, so it is not a rounding error:
    fired every 10 turns against a 4,000-token window, it adds roughly a tenth
    to a tenant's token bill and was recorded as zero."""

    class _Llm:
        async def generate(self, *_a, **_k):
            from app.providers.base import LLMResult

            return LLMResult(text="Customer asked about hours.", prompt_tokens=3800,
                             completion_tokens=40)

    text, usage = await pipeline.refresh_summary_with_usage(
        _Llm(), prior_summary=None, recent=[], model="m"
    )

    assert text == "Customer asked about hours."
    assert usage.prompt_tokens == 3800
    assert usage.completion_tokens == 40


async def test_summary_refresh_failure_costs_nothing_and_keeps_the_old_summary():
    class _Broken:
        async def generate(self, *_a, **_k):
            raise RuntimeError("provider down")

    text, usage = await pipeline.refresh_summary_with_usage(
        _Broken(), prior_summary="the old one", recent=[], model="m"
    )

    assert text == "the old one"
    assert usage.prompt_tokens == 0 and usage.completion_tokens == 0
