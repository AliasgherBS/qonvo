"""Agent pipeline — grounded RAG + tool-calling reply loop (DESIGN.md §5.4).

Orchestration (``run_pipeline``) loads tenant persona + conversation state,
applies the early-return gates (pause/takeover, business hours, hard quota),
retrieves grounding context, runs the bounded tool loop, persists everything,
and sends the reply through the injected :class:`SendGateway`. Every step that
can be reasoned about without a database is a pure function below it so the
logic is unit-testable without Postgres.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.core.tenancy import tenant_session
from app.models.conversation import Conversation, Message
from app.models.enums import ConversationState, MessageAuthor, MessageDirection, MessageType
from app.models.ops import AnalyticsEvent, UsageCounter
from app.models.tenant import TenantConfig
from app.models.whatsapp import WhatsAppSession
from app.providers.base import ChatMessage, LLMProvider, LLMResult, ToolCall
from app.providers.registry import resolve_embedding, resolve_llm
from app.skills.registry import SkillContext, execute_skill
from app.skills.registry import enabled_tools as skill_enabled_tools
from app.waha.send_gateway import DailyCapExceeded, SendGateway, SessionPacing

CATCH_UP_REPLY = "Sorry for the delay — how can I help?"
QUOTA_EXCEEDED_REPLY = (
    "We're at our messaging limit for now — I've let the team know and they'll "
    "reach out to you directly."
)
GROUNDING_INSTRUCTION = (
    "Answer ONLY using the business knowledge provided below. If the answer is "
    "not covered by this knowledge, say you'll connect them with the team and "
    "call the human_handoff tool — never invent facts, prices, policies, or "
    "availability."
)


@dataclass(slots=True)
class InboundFragment:
    """One buffered inbound fragment (already deduped)."""

    message_id: str
    type: str = "text"
    body: str = ""
    media_url: str | None = None
    timestamp: float | None = None


@dataclass(slots=True)
class PipelineResult:
    reply_text: str
    reply_voice: bool = False
    tokens: int = 0
    cost: float = 0.0
    meta: dict = field(default_factory=dict)


def coalesce_fragments(fragments: list[InboundFragment]) -> str:
    """Join buffered fragments into a single turn, in arrival order (§5.2).

    Voice fragments would be transcribed first (STT) in Phase 2; here their
    placeholder text is included so the coalescing behaviour is exercised.
    """
    parts = [f.body.strip() for f in fragments if f.body and f.body.strip()]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Gates (DESIGN.md §5.4 step 4) — pure, unit-testable
# --------------------------------------------------------------------------- #
def should_auto_resume(
    state: ConversationState, paused_until: datetime | None, *, now: datetime
) -> bool:
    """True when a paused conversation's auto-resume TTL has elapsed (§5.5)."""
    return (
        state != ConversationState.bot_active
        and paused_until is not None
        and now >= paused_until
    )


def is_paused(state: ConversationState, paused_until: datetime | None, *, now: datetime) -> bool:
    """True when the bot must not reply: paused/needs_human and not yet auto-resumed."""
    if state == ConversationState.bot_active:
        return False
    return not should_auto_resume(state, paused_until, now=now)


def _parse_hhmm(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def is_within_business_hours(business_hours: dict[str, Any], *, now: datetime) -> bool:
    """``business_hours`` shape: ``{"enabled": bool, "timezone": "UTC",
    "hours": {"mon": [["09:00", "17:00"]], ...}}``. Missing/disabled → always open.
    """
    if not business_hours or not business_hours.get("enabled"):
        return True

    tz_name = business_hours.get("timezone", "UTC")
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — unknown/invalid tz name falls back to UTC
        tz = UTC
    local = now.astimezone(tz)
    day_key = local.strftime("%a").lower()

    windows = (business_hours.get("hours") or {}).get(day_key, [])
    current = local.time()
    return any(_parse_hhmm(start) <= current <= _parse_hhmm(end) for start, end in windows)


def business_hours_closed_reply(business_hours: dict[str, Any]) -> str:
    return business_hours.get("closed_message") or (
        "Thanks for reaching out — we're closed right now, but we'll get back "
        "to you as soon as we're open."
    )


def is_hard_quota_exceeded(entitlements: dict[str, Any], messages_this_period: int) -> bool:
    """``entitlements`` shape: ``{"monthly_message_quota": int, ...}``. No
    quota configured → never blocks."""
    quota = entitlements.get("monthly_message_quota")
    if not quota:
        return False
    return messages_this_period >= quota


# --------------------------------------------------------------------------- #
# Grounding prompt assembly (DESIGN.md §5.4 step 6)
# --------------------------------------------------------------------------- #
def build_system_prompt(
    *,
    business_name: str | None,
    persona: str | None,
    tone: str | None,
    custom_instructions: str | None,
    primary_language: str,
    context_block: str,
) -> str:
    lines = [f"You are the AI customer representative for {business_name or 'this business'}."]
    if persona:
        lines.append(persona)
    if tone:
        lines.append(f"Tone: {tone}.")
    if custom_instructions:
        lines.append(custom_instructions)
    lines.append(GROUNDING_INSTRUCTION)
    lines.append(
        "Always reply in the customer's language; default to "
        f"{primary_language} only if the language is unclear."
    )
    lines.append(
        "Keep replies concise and conversational, in WhatsApp style — short "
        "paragraphs, no markdown headers or bullet-heavy formatting."
    )
    if context_block:
        lines.append("Business knowledge:\n" + context_block)
    else:
        lines.append("No relevant business knowledge was found for this question.")
    return "\n\n".join(lines)


# --------------------------------------------------------------------------- #
# History windowing (DESIGN.md §5.4 step 6)
# --------------------------------------------------------------------------- #
def _approx_tokens(message: Message) -> int:
    if message.tokens:
        return message.tokens
    text = message.body or message.transcript or ""
    return len(text.split())


def window_history(
    messages: list[Message],
    *,
    max_messages: int | None = None,
    max_tokens: int | None = None,
) -> list[Message]:
    """Trim to the last ``max_messages`` *and* ~``max_tokens``, oldest dropped first."""
    max_messages = max_messages if max_messages is not None else settings.history_window_messages
    max_tokens = max_tokens if max_tokens is not None else settings.history_window_tokens

    recent = list(messages)[-max_messages:] if max_messages else list(messages)
    total = sum(_approx_tokens(m) for m in recent)
    while len(recent) > 1 and total > max_tokens:
        dropped = recent.pop(0)
        total -= _approx_tokens(dropped)
    return recent


def to_chat_messages(messages: list[Message]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for m in messages:
        role = "user" if m.author == MessageAuthor.customer else "assistant"
        content = m.body or m.transcript or ""
        out.append(ChatMessage(role=role, content=content))
    return out


def should_refresh_summary(turn_number: int, *, refresh_every: int | None = None) -> bool:
    refresh_every = refresh_every if refresh_every is not None else settings.summary_refresh_turns
    return refresh_every > 0 and turn_number % refresh_every == 0


# --------------------------------------------------------------------------- #
# Cost (DESIGN.md §13)
# --------------------------------------------------------------------------- #
def compute_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    pricing: dict[str, dict[str, dict[str, float]]] | None = None,
) -> float:
    """USD cost from the per-provider-per-model $/1K-token pricing table."""
    pricing = pricing if pricing is not None else settings.llm_pricing
    rates = (pricing.get(provider) or {}).get(model)
    if not rates:
        return 0.0
    return (prompt_tokens / 1000) * rates.get("input", 0.0) + (
        completion_tokens / 1000
    ) * rates.get("output", 0.0)


# --------------------------------------------------------------------------- #
# Tool loop (DESIGN.md §5.4 step 7 — max 5 iterations)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ToolLoopResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    transcript: list[ChatMessage]
    iterations: int
    tool_results: list[dict[str, Any]] = field(default_factory=list)


ToolDispatcher = Callable[[ToolCall], Awaitable[dict[str, Any]]]


async def run_tool_loop(
    llm: LLMProvider,
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    dispatch: ToolDispatcher,
    *,
    max_iterations: int | None = None,
    model: str | None = None,
) -> ToolLoopResult:
    """Call the LLM, executing any requested tool calls, until a final answer.

    Stops after ``max_iterations`` rounds even without a final text answer,
    returning the last result as-is (a bounded loop is required — DESIGN.md
    §5.4 — so a misbehaving model can never spin forever).
    """
    max_iterations = (
        max_iterations if max_iterations is not None else settings.tool_loop_max_iterations
    )
    working = list(messages)
    prompt_tokens = 0
    completion_tokens = 0
    tool_results: list[dict[str, Any]] = []
    last = LLMResult(text="")

    for i in range(max_iterations):
        last = await llm.generate(working, tools=tools or None, model=model)
        prompt_tokens += last.prompt_tokens
        completion_tokens += last.completion_tokens
        if not last.tool_calls:
            return ToolLoopResult(
                text=last.text,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                transcript=working,
                iterations=i + 1,
                tool_results=tool_results,
            )

        working.append(
            ChatMessage(role="assistant", content=last.text, tool_calls=last.tool_calls)
        )
        for call in last.tool_calls:
            result = await dispatch(call)
            tool_results.append(result)
            working.append(
                ChatMessage(
                    role="tool",
                    content=json.dumps(result),
                    tool_call_id=call.id,
                    name=call.name,
                )
            )

    return ToolLoopResult(
        text=last.text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        transcript=working,
        iterations=max_iterations,
        tool_results=tool_results,
    )


# --------------------------------------------------------------------------- #
# DB-backed orchestration
# --------------------------------------------------------------------------- #
async def _get_or_create_conversation(
    db: AsyncSession, tenant_id: uuid.UUID, session_row: WhatsAppSession, chat_id: str
) -> Conversation:
    existing = (
        await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.session_id == session_row.id,
                Conversation.chat_id == chat_id,
                Conversation.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    conversation = Conversation(tenant_id=tenant_id, session_id=session_row.id, chat_id=chat_id)
    db.add(conversation)
    await db.flush()
    return conversation


async def _persist_inbound(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    conversation: Conversation,
    fragments: list[InboundFragment],
) -> None:
    for fragment in fragments:
        try:
            msg_type = MessageType(fragment.type)
        except ValueError:
            msg_type = MessageType.other
        wa_timestamp = (
            datetime.fromtimestamp(fragment.timestamp, tz=UTC) if fragment.timestamp else None
        )
        db.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                wa_message_id=fragment.message_id,
                direction=MessageDirection.inbound,
                author=MessageAuthor.customer,
                type=msg_type,
                body=fragment.body,
                media_key=fragment.media_url,
                wa_timestamp=wa_timestamp,
            )
        )


async def _bump_usage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    messages_in: int,
    messages_out: int,
    tokens: int,
    cost: float,
) -> None:
    today = date.today()
    row = (
        await db.execute(
            select(UsageCounter).where(
                UsageCounter.tenant_id == tenant_id, UsageCounter.day == today
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = UsageCounter(tenant_id=tenant_id, day=today)
        db.add(row)
    row.messages_in += messages_in
    row.messages_out += messages_out
    row.tokens += tokens
    row.cost = float(row.cost or 0) + cost


async def _messages_this_month(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    today = date.today()
    rows = (
        (
            await db.execute(
                select(UsageCounter).where(
                    UsageCounter.tenant_id == tenant_id,
                    UsageCounter.day >= today.replace(day=1),
                )
            )
        )
        .scalars()
        .all()
    )
    return sum(r.messages_in + r.messages_out for r in rows)


async def run_pipeline(
    fragments: list[InboundFragment],
    *,
    session: str,
    chat_id: str,
    tenant_id: str,
    send_gateway: SendGateway,
    catch_up: bool = False,
) -> PipelineResult:
    """Produce (and send) a grounded reply for the coalesced fragments.

    Owns the full turn: gates → RAG → tool loop → persistence → send. Runs
    inside a single tenant-scoped transaction (RLS-enforced, DESIGN.md §3).
    """
    tenant_uuid = uuid.UUID(tenant_id)
    bound = logger.bind(session=session, chat_id=chat_id, tenant_id=tenant_id)

    async with tenant_session(tenant_uuid) as db:
        session_row = (
            await db.execute(
                select(WhatsAppSession).where(WhatsAppSession.session_name == session)
            )
        ).scalar_one_or_none()
        if session_row is None:
            bound.error("no whatsapp_sessions row for session — cannot process")
            return PipelineResult(reply_text="", meta={"gate": "unknown_session"})

        tenant_config = (
            await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_uuid))
        ).scalar_one_or_none()

        conversation = await _get_or_create_conversation(db, tenant_uuid, session_row, chat_id)
        await _persist_inbound(db, tenant_uuid, conversation, fragments)

        now = datetime.now(UTC)

        # --- Gate: pause / takeover (§5.5) ---
        if should_auto_resume(conversation.state, conversation.paused_until, now=now):
            conversation.state = ConversationState.bot_active
            conversation.paused_until = None
        if is_paused(conversation.state, conversation.paused_until, now=now):
            conversation.last_activity_at = now
            bound.info(f"conversation paused ({conversation.state}) — no reply")
            return PipelineResult(
                reply_text="", meta={"gate": "paused", "state": str(conversation.state)}
            )

        # --- Gate: hard quota (§13) ---
        entitlements = tenant_config.entitlements if tenant_config else {}
        messages_this_period = await _messages_this_month(db, tenant_uuid)
        if is_hard_quota_exceeded(entitlements, messages_this_period):
            conversation.last_activity_at = now
            db.add(
                Message(
                    tenant_id=tenant_uuid,
                    conversation_id=conversation.id,
                    direction=MessageDirection.outbound,
                    author=MessageAuthor.bot,
                    type=MessageType.text,
                    body=QUOTA_EXCEEDED_REPLY,
                    meta={"auto_reply": "quota_exceeded"},
                )
            )
            await _bump_usage(
                db, tenant_uuid, messages_in=len(fragments), messages_out=1, tokens=0, cost=0.0
            )
            await _send(bound, send_gateway, session, chat_id, QUOTA_EXCEEDED_REPLY)
            return PipelineResult(reply_text=QUOTA_EXCEEDED_REPLY, meta={"gate": "quota_exceeded"})

        # --- History (for both the business-hours check and the LLM context) ---
        history_rows = (
            (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        history_rows = list(reversed(history_rows))

        # --- Gate: business hours (§5.2, auto-reply once per conversation) ---
        business_hours = tenant_config.business_hours if tenant_config else {}
        if business_hours and not is_within_business_hours(business_hours, now=now):
            already_replied = any(
                m.meta.get("auto_reply") == "business_hours" for m in history_rows
            )
            if not already_replied:
                reply = business_hours_closed_reply(business_hours)
                conversation.last_activity_at = now
                db.add(
                    Message(
                        tenant_id=tenant_uuid,
                        conversation_id=conversation.id,
                        direction=MessageDirection.outbound,
                        author=MessageAuthor.bot,
                        type=MessageType.text,
                        body=reply,
                        meta={"auto_reply": "business_hours"},
                    )
                )
                await _bump_usage(
                    db, tenant_uuid, messages_in=len(fragments), messages_out=1, tokens=0, cost=0.0
                )
                await _send(bound, send_gateway, session, chat_id, reply)
                return PipelineResult(reply_text=reply, meta={"gate": "business_hours"})
            conversation.last_activity_at = now
            return PipelineResult(reply_text="", meta={"gate": "business_hours_already_replied"})

        # --- Catch-up (staleness guard, §5.3) ---
        if catch_up:
            conversation.last_activity_at = now
            db.add(
                Message(
                    tenant_id=tenant_uuid,
                    conversation_id=conversation.id,
                    direction=MessageDirection.outbound,
                    author=MessageAuthor.bot,
                    type=MessageType.text,
                    body=CATCH_UP_REPLY,
                    meta={"catch_up": True},
                )
            )
            await _bump_usage(
                db, tenant_uuid, messages_in=len(fragments), messages_out=1, tokens=0, cost=0.0
            )
            await _send(bound, send_gateway, session, chat_id, CATCH_UP_REPLY)
            return PipelineResult(reply_text=CATCH_UP_REPLY, meta={"catch_up": True})

        # --- RAG retrieve (§6) ---
        coalesced = coalesce_fragments(fragments)
        embedder = resolve_embedding(tenant_config)
        from app.agent.rag import build_context_block, retrieve

        chunks = await retrieve(db, tenant_uuid, coalesced, embedder=embedder)
        if not chunks and coalesced:
            db.add(
                AnalyticsEvent(
                    tenant_id=tenant_uuid,
                    event_type="knowledge_gap",
                    conversation_id=conversation.id,
                    occurred_at=now,
                    data={"question": coalesced},
                )
            )
        context_block = build_context_block(chunks)

        # --- Grounding prompt + windowed history (§5.4 steps 6–7) ---
        system_prompt = build_system_prompt(
            business_name=tenant_config.business_name if tenant_config else None,
            persona=tenant_config.persona if tenant_config else None,
            tone=tenant_config.tone if tenant_config else None,
            custom_instructions=tenant_config.custom_instructions if tenant_config else None,
            primary_language=tenant_config.primary_language if tenant_config else "en",
            context_block=context_block,
        )
        windowed = window_history(history_rows)
        images = [f.media_url for f in fragments if f.type == "image" and f.media_url]
        llm_messages = [
            ChatMessage(role="system", content=system_prompt),
            *to_chat_messages(windowed),
            ChatMessage(role="user", content=coalesced, images=images),
        ]

        tools = await skill_enabled_tools(db, tenant_uuid)
        llm = resolve_llm(tenant_config)

        async def dispatch(call: ToolCall) -> dict[str, Any]:
            ctx = SkillContext(
                db=db,
                tenant_id=tenant_uuid,
                conversation_id=conversation.id,
                idempotency_key=f"{conversation.id}:{call.id}",
                conversation=conversation,
                tenant_config=tenant_config,
                send_gateway=send_gateway,
                session_name=session,
                chat_id=chat_id,
            )
            try:
                return await execute_skill(ctx, call.name, call.arguments)
            except Exception as exc:  # noqa: BLE001 — surfaced to the model, not raised
                bound.warning(f"skill {call.name} failed: {exc}")
                return {"status": "error", "message": str(exc)}

        loop_result = await run_tool_loop(llm, llm_messages, tools, dispatch)
        reply_text = loop_result.text or "Sorry, I didn't catch that — could you rephrase?"

        provider_name = (
            tenant_config.llm_provider
            if tenant_config and tenant_config.llm_provider
            else settings.llm_provider
        )
        model_name = (
            tenant_config.llm_model
            if tenant_config and tenant_config.llm_model
            else settings.llm_model
        )
        total_tokens = loop_result.prompt_tokens + loop_result.completion_tokens
        cost = compute_cost(
            provider_name, model_name, loop_result.prompt_tokens, loop_result.completion_tokens
        )

        # --- Persist outbound + usage, refresh rolling summary (§5.4 step 6, §13) ---
        conversation.last_activity_at = now
        db.add(
            Message(
                tenant_id=tenant_uuid,
                conversation_id=conversation.id,
                direction=MessageDirection.outbound,
                author=MessageAuthor.bot,
                type=MessageType.text,
                body=reply_text,
                tokens=total_tokens,
                cost=cost,
                meta={"knowledge_gap": True} if not chunks else {},
            )
        )
        await _bump_usage(
            db,
            tenant_uuid,
            messages_in=len(fragments),
            messages_out=1,
            tokens=total_tokens,
            cost=cost,
        )

        prior_bot_turns = sum(1 for m in history_rows if m.author == MessageAuthor.bot)
        turn_number = prior_bot_turns + 1
        if should_refresh_summary(turn_number):
            try:
                conversation.summary = await _refresh_summary(
                    llm, conversation.summary, windowed, model=model_name
                )
            except Exception as exc:  # noqa: BLE001 — summary refresh must not break the turn
                bound.warning(f"summary refresh failed: {exc}")

        await _send(bound, send_gateway, session, chat_id, reply_text)

        return PipelineResult(
            reply_text=reply_text,
            tokens=total_tokens,
            cost=cost,
            meta={"chunks": len(chunks), "tool_iterations": loop_result.iterations},
        )


async def _refresh_summary(
    llm: LLMProvider, prior_summary: str | None, recent: list[Message], *, model: str | None
) -> str:
    transcript = "\n".join(
        f"{'Customer' if m.author == MessageAuthor.customer else 'Agent'}: "
        f"{m.body or m.transcript or ''}"
        for m in recent
    )
    prompt = (
        "Summarize this WhatsApp support conversation in 2-3 sentences for future "
        "context. Keep names, requests, and commitments made.\n\n"
        f"Prior summary: {prior_summary or '(none)'}\n\nRecent messages:\n{transcript}"
    )
    result = await llm.generate([ChatMessage(role="user", content=prompt)], model=model)
    return result.text.strip() or (prior_summary or "")


async def _send(bound: Any, gateway: SendGateway, session: str, chat_id: str, text: str) -> None:
    try:
        await gateway.send_text(session, chat_id, text, pacing=SessionPacing())
    except DailyCapExceeded:
        bound.warning("daily cap reached — reply suppressed")


__all__ = [
    "CATCH_UP_REPLY",
    "GROUNDING_INSTRUCTION",
    "QUOTA_EXCEEDED_REPLY",
    "InboundFragment",
    "PipelineResult",
    "ToolLoopResult",
    "build_system_prompt",
    "business_hours_closed_reply",
    "coalesce_fragments",
    "compute_cost",
    "is_hard_quota_exceeded",
    "is_paused",
    "is_within_business_hours",
    "run_pipeline",
    "run_tool_loop",
    "should_auto_resume",
    "should_refresh_summary",
    "to_chat_messages",
    "window_history",
]
