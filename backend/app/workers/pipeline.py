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
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from datetime import time as dt_time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.service import get_subscription
from app.billing.state import service_state
from app.core import obs
from app.core.config import settings
from app.core.logging import logger
from app.core.tenancy import tenant_session
from app.models.conversation import Conversation, Message
from app.models.enums import ConversationState, MessageAuthor, MessageDirection, MessageType
from app.models.ops import AnalyticsEvent, UsageCounter
from app.models.tenant import Tenant, TenantConfig
from app.models.whatsapp import WhatsAppSession
from app.providers.base import ChatMessage, LLMProvider, LLMResult, ToolCall
from app.providers.registry import (
    resolve_embedding,
    resolve_llm,
    resolve_llm_identity,
    voice_reply_mode,
)
from app.skills.registry import SkillContext, execute_skill
from app.skills.registry import enabled_tools as skill_enabled_tools
from app.waha.send_gateway import (
    DailyCapExceeded,
    SendGateway,
    SessionPacing,
    pacing_for_session,
)

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

    Voice fragments are transcribed (STT) into ``body`` before this runs (Phase 2),
    so their transcript is included like any text fragment.
    """
    parts = [f.body.strip() for f in fragments if f.body and f.body.strip()]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Voice (Phase 2, DESIGN.md §2 voice loop) — pure helpers
# --------------------------------------------------------------------------- #
_VOICE_TYPES = {"voice", "ptt", "audio"}


def is_voice_fragment(fragment: InboundFragment) -> bool:
    return bool(fragment.media_url) and fragment.type in _VOICE_TYPES


def should_reply_voice(mode: str, *, inbound_had_voice: bool) -> bool:
    """ "always" → always; "never" → never; "match" → mirror the customer."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    return inbound_had_voice


async def _transcribe_voice_fragments(
    fragments: list[InboundFragment],
    tenant_config: Any,
    waha: Any,
    bound: Any,
) -> tuple[bool, int]:
    """STT every voice fragment in place (sets ``body``, normalizes ``type`` to
    "voice"). Returns ``(had_voice, estimated_seconds)`` — the second is the
    metered inbound voice duration for this turn (0 when nothing transcribed).
    A missing STT provider or a failed download/transcription degrades to a
    text-only turn; an oversized note is skipped before STT (abuse guard).
    """
    voice_frags = [f for f in fragments if is_voice_fragment(f)]
    if not voice_frags:
        return False, 0
    if waha is None:
        bound.warning("voice message received but no WAHA client for media download")
        return True, 0

    from app.providers.registry import resolve_stt

    stt = resolve_stt(tenant_config)
    if stt is None:
        bound.warning("voice message received but no STT provider configured")
        return True, 0

    total_seconds = 0
    for fragment in voice_frags:
        try:
            audio = await waha.download_media(fragment.media_url)
            if len(audio) > settings.max_inbound_audio_bytes:
                bound.warning(
                    f"voice note too large ({len(audio)} bytes > "
                    f"{settings.max_inbound_audio_bytes}) — skipping transcription"
                )
                fragment.type = "voice"
                continue
            result = await stt.transcribe(audio)
            fragment.body = result.text or ""
            fragment.type = "voice"
            total_seconds += max(1, len(audio) // settings.voice_bytes_per_second)
            bound.info(f"transcribed voice fragment ({len(fragment.body)} chars)")
        except Exception as exc:  # noqa: BLE001 — degrade to text-only, don't crash the turn
            bound.warning(f"voice transcription failed: {exc}")
            fragment.type = "voice"
    if hasattr(stt, "aclose"):
        await stt.aclose()
    return True, total_seconds


_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_image_mime(data: bytes) -> str:
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"  # WhatsApp photos are JPEG by default


async def _images_as_data_uris(
    fragments: list[InboundFragment], waha: Any, bound: Any
) -> list[str]:
    """Download inbound image fragments and inline them as base64 data URIs.

    The raw ``media_url`` points at WAHA's internal host (``waha:3000``), which
    the LLM provider can't fetch — so vision silently saw nothing. Mirror the
    voice path: download the bytes here and hand the model a self-contained
    data URI. Oversized images and download failures degrade to a text-only turn.
    """
    import base64

    image_frags = [f for f in fragments if f.type == "image" and f.media_url]
    if not image_frags:
        return []
    if waha is None:
        bound.warning("image message received but no WAHA client for media download")
        return []
    uris: list[str] = []
    for fragment in image_frags:
        try:
            data = await waha.download_media(fragment.media_url)
            if len(data) > settings.max_inbound_image_bytes:
                bound.warning(f"image too large ({len(data)} bytes) — skipping vision")
                continue
            mime = _sniff_image_mime(data)
            uris.append(f"data:{mime};base64,{base64.b64encode(data).decode()}")
        except Exception as exc:  # noqa: BLE001 — degrade to text-only, don't crash the turn
            bound.warning(f"image download failed: {exc}")
    return uris


# --------------------------------------------------------------------------- #
# Gates (DESIGN.md §5.4 step 4) — pure, unit-testable
# --------------------------------------------------------------------------- #
def should_auto_resume(
    state: ConversationState, paused_until: datetime | None, *, now: datetime
) -> bool:
    """True when a paused conversation's auto-resume TTL has elapsed (§5.5)."""
    return (
        state != ConversationState.bot_active and paused_until is not None and now >= paused_until
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
    conversation_summary: str | None = None,
) -> str:
    lines = [f"You are the AI customer representative for {business_name or 'this business'}."]
    if persona:
        lines.append(persona)
    if tone:
        lines.append(f"Tone: {tone}.")
    if custom_instructions:
        lines.append(custom_instructions)
    if conversation_summary:
        # Rolling summary of turns that have scrolled out of the history window
        # (§5.4 step 6) — gives the model long-term memory of this conversation.
        lines.append("Summary of the conversation so far:\n" + conversation_summary)
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
        # A miss silently records $0.00 for every turn — loud so it's caught, not
        # discovered months later in flat-zero analytics. Add the model to
        # settings.llm_pricing to fix.
        logger.warning(
            f"no pricing for {provider}/{model} — recording $0.00; add it to llm_pricing"
        )
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

        working.append(ChatMessage(role="assistant", content=last.text, tool_calls=last.tool_calls))
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
    voice_seconds: int = 0,
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
    # A fresh ORM row has None counters until server defaults apply on flush —
    # guard every field the way ``cost`` already does (caught live).
    row.messages_in = (row.messages_in or 0) + messages_in
    row.messages_out = (row.messages_out or 0) + messages_out
    row.tokens = (row.tokens or 0) + tokens
    row.cost = float(row.cost or 0) + cost
    row.voice_seconds = (row.voice_seconds or 0) + voice_seconds


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
    waha: Any = None,
) -> PipelineResult:
    """Time the turn and record cross-process metrics, then delegate.

    Latency, throughput, and gate counters are captured here uniformly for every
    path (gated or full reply); success-only metrics (cost/tokens/voice) are
    recorded inside. Metrics failures never affect the reply.
    """
    start = time.perf_counter()
    result = await _run_pipeline_inner(
        fragments,
        session=session,
        chat_id=chat_id,
        tenant_id=tenant_id,
        send_gateway=send_gateway,
        catch_up=catch_up,
        waha=waha,
    )
    await obs.observe("qonvo_pipeline_duration_seconds", time.perf_counter() - start)
    await obs.incr("qonvo_messages_processed_total", {"direction": "inbound"}, len(fragments))
    if result.reply_text:
        await obs.incr("qonvo_replies_sent_total")
    gate = result.meta.get("gate")
    if gate:
        await obs.incr("qonvo_pipeline_gate_total", {"gate": str(gate)})
    return result


async def _run_pipeline_inner(
    fragments: list[InboundFragment],
    *,
    session: str,
    chat_id: str,
    tenant_id: str,
    send_gateway: SendGateway,
    catch_up: bool = False,
    waha: Any = None,
) -> PipelineResult:
    """Produce (and send) a grounded reply for the coalesced fragments.

    Owns the full turn: gates → RAG → tool loop → persistence → send. Runs
    inside a single tenant-scoped transaction (RLS-enforced, DESIGN.md §3).
    """
    tenant_uuid = uuid.UUID(tenant_id)
    bound = logger.bind(session=session, chat_id=chat_id, tenant_id=tenant_id)

    async with tenant_session(tenant_uuid) as db:
        session_row = (
            await db.execute(select(WhatsAppSession).where(WhatsAppSession.session_name == session))
        ).scalar_one_or_none()
        if session_row is None:
            bound.error("no whatsapp_sessions row for session — cannot process")
            return PipelineResult(reply_text="", meta={"gate": "unknown_session"})

        # Every outbound below — gate notices, catch-up, the reply itself — is
        # paced by this session's configured cap and warm-up stage (§5.6).
        pacing = pacing_for_session(session_row)

        tenant_config = (
            await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_uuid))
        ).scalar_one_or_none()

        conversation = await _get_or_create_conversation(db, tenant_uuid, session_row, chat_id)
        # Voice-in: transcribe before persisting so the inbound Message stores the
        # transcript as its body (§2 voice loop).
        inbound_had_voice, voice_seconds = await _transcribe_voice_fragments(
            fragments, tenant_config, waha, bound
        )
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

        # --- Gate: entitlement to service (§9 billing, admin lifecycle) ---
        # Suspended, expired trial, unpaid past the grace window, or cancelled
        # past the paid-for period → the bot goes silent. We deliberately do NOT
        # message the customer about the business's account status.
        tenant_row = (
            await db.execute(
                select(Tenant.status, Tenant.plan, Tenant.trial_ends_at).where(
                    Tenant.id == tenant_uuid
                )
            )
        ).one_or_none()
        if tenant_row is not None:
            entitlement = service_state(
                tenant_status=tenant_row.status,
                plan=tenant_row.plan,
                trial_ends_at=tenant_row.trial_ends_at,
                subscription=await get_subscription(db, tenant_uuid),
                now=now,
            )
            if not entitlement.allowed:
                bound.info(f"service blocked ({entitlement.gate}) — bot silent")
                return PipelineResult(reply_text="", meta={"gate": entitlement.gate})

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
                db,
                tenant_uuid,
                messages_in=len(fragments),
                messages_out=1,
                tokens=0,
                cost=0.0,
                voice_seconds=voice_seconds,
            )
            await _send(bound, send_gateway, session, chat_id, QUOTA_EXCEEDED_REPLY, pacing)
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
                    db,
                    tenant_uuid,
                    messages_in=len(fragments),
                    messages_out=1,
                    tokens=0,
                    cost=0.0,
                    voice_seconds=voice_seconds,
                )
                await _send(bound, send_gateway, session, chat_id, reply, pacing)
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
                db,
                tenant_uuid,
                messages_in=len(fragments),
                messages_out=1,
                tokens=0,
                cost=0.0,
                voice_seconds=voice_seconds,
            )
            await _send(bound, send_gateway, session, chat_id, CATCH_UP_REPLY, pacing)
            return PipelineResult(reply_text=CATCH_UP_REPLY, meta={"catch_up": True})

        coalesced = coalesce_fragments(fragments)

        # --- Gate: reminder opt-out ("stop") (§5.7) ---
        from app.agent.reminders import is_stop_message

        if is_stop_message(coalesced):
            from app.models.business import ReminderSuppression

            phone = chat_id.split("@", 1)[0]
            already = (
                await db.execute(
                    select(ReminderSuppression).where(
                        ReminderSuppression.tenant_id == tenant_uuid,
                        ReminderSuppression.phone == phone,
                    )
                )
            ).scalar_one_or_none()
            if already is None:
                db.add(
                    ReminderSuppression(
                        tenant_id=tenant_uuid, phone=phone, reason="customer opted out via chat"
                    )
                )
            reply = "Done — you won't get reminders from us anymore. Message us any time."
            conversation.last_activity_at = now
            db.add(
                Message(
                    tenant_id=tenant_uuid,
                    conversation_id=conversation.id,
                    direction=MessageDirection.outbound,
                    author=MessageAuthor.bot,
                    type=MessageType.text,
                    body=reply,
                    meta={"auto_reply": "reminder_optout"},
                )
            )
            await _bump_usage(
                db,
                tenant_uuid,
                messages_in=len(fragments),
                messages_out=1,
                tokens=0,
                cost=0.0,
                voice_seconds=voice_seconds,
            )
            await _send(bound, send_gateway, session, chat_id, reply, pacing)
            return PipelineResult(reply_text=reply, meta={"gate": "reminder_optout"})

        # --- RAG retrieve (§6) ---
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
            conversation_summary=conversation.summary,
        )
        windowed = window_history(history_rows)
        images = await _images_as_data_uris(fragments, waha, bound)
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
                out = await execute_skill(ctx, call.name, call.arguments)
                await obs.incr(
                    "qonvo_skill_invocations_total",
                    {"skill": call.name, "outcome": str(out.get("status", "ok"))},
                )
                return out
            except Exception as exc:  # noqa: BLE001 — surfaced to the model, not raised
                bound.warning(f"skill {call.name} failed: {exc}")
                await obs.incr(
                    "qonvo_skill_invocations_total", {"skill": call.name, "outcome": "error"}
                )
                return {"status": "error", "message": str(exc)}

        try:
            loop_result = await run_tool_loop(llm, llm_messages, tools, dispatch)
        except Exception:
            await obs.incr("qonvo_provider_errors_total", {"kind": "llm"})
            raise
        # .strip() so a whitespace-only model output (seen when an untranscribed
        # voice note yields an empty user turn) falls back instead of sending a
        # blank WhatsApp message.
        reply_text = (loop_result.text or "").strip() or (
            "Sorry, I didn't catch that — could you rephrase?"
        )

        # Same resolution resolve_llm used to build the provider, so the cost is
        # priced against the model that actually answered (§13).
        provider_name, model_name = resolve_llm_identity(tenant_config)
        total_tokens = loop_result.prompt_tokens + loop_result.completion_tokens
        cost = compute_cost(
            provider_name, model_name, loop_result.prompt_tokens, loop_result.completion_tokens
        )

        # --- Voice-out (§2): synthesize when the customer sent voice / tenant opts in ---
        reply_voice = should_reply_voice(
            voice_reply_mode(tenant_config), inbound_had_voice=inbound_had_voice
        )
        audio_b64 = (
            await _synthesize_reply(reply_text, tenant_config, bound) if reply_voice else None
        )
        was_voice = audio_b64 is not None
        if was_voice and audio_b64:
            # base64 → raw bytes ≈ len * 3/4; meter the synthesized reply too.
            out_bytes = (len(audio_b64) * 3) // 4
            voice_seconds += max(1, out_bytes // settings.voice_bytes_per_second)

        # --- Persist outbound + usage, refresh rolling summary (§5.4 step 6, §13) ---
        conversation.last_activity_at = now
        db.add(
            Message(
                tenant_id=tenant_uuid,
                conversation_id=conversation.id,
                direction=MessageDirection.outbound,
                author=MessageAuthor.bot,
                type=MessageType.voice if was_voice else MessageType.text,
                body=reply_text,
                transcript=reply_text if was_voice else None,
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
            voice_seconds=voice_seconds,
        )
        # Cross-process metrics (Prometheus): success-path spend + throughput.
        if cost:
            await obs.incr("qonvo_llm_cost_usd_total", value=float(cost))
        if total_tokens:
            await obs.incr("qonvo_llm_tokens_total", value=float(total_tokens))
        if voice_seconds:
            await obs.incr("qonvo_voice_seconds_total", value=float(voice_seconds))

        prior_bot_turns = sum(1 for m in history_rows if m.author == MessageAuthor.bot)
        turn_number = prior_bot_turns + 1
        if should_refresh_summary(turn_number):
            try:
                conversation.summary = await _refresh_summary(
                    llm, conversation.summary, windowed, model=model_name
                )
            except Exception as exc:  # noqa: BLE001 — summary refresh must not break the turn
                bound.warning(f"summary refresh failed: {exc}")

        if was_voice:
            await _send_voice(bound, send_gateway, session, chat_id, audio_b64, pacing)
        else:
            await _send(bound, send_gateway, session, chat_id, reply_text, pacing)

        return PipelineResult(
            reply_text=reply_text,
            reply_voice=was_voice,
            tokens=total_tokens,
            cost=cost,
            meta={
                "chunks": len(chunks),
                "tool_iterations": loop_result.iterations,
                "voice": was_voice,
            },
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


async def _send(
    bound: Any,
    gateway: SendGateway,
    session: str,
    chat_id: str,
    text: str,
    pacing: SessionPacing,
) -> None:
    try:
        await gateway.send_text(session, chat_id, text, pacing=pacing)
    except DailyCapExceeded:
        bound.warning("daily cap reached — reply suppressed")
    except Exception:
        await obs.incr("qonvo_whatsapp_send_failures_total")
        raise


async def _synthesize_reply(text: str, tenant_config: Any, bound: Any) -> str | None:
    """TTS the reply → base64 audio, or None to fall back to text (§2)."""
    import base64

    from app.providers.registry import resolve_tts

    tts = resolve_tts(tenant_config)
    if tts is None:
        bound.info("voice reply wanted but no TTS provider configured — sending text")
        return None
    try:
        audio = await tts.synthesize(text)
        return base64.b64encode(audio).decode()
    except Exception as exc:  # noqa: BLE001 — degrade to text, never drop the reply
        bound.warning(f"TTS synthesis failed, falling back to text: {exc}")
        return None
    finally:
        if hasattr(tts, "aclose"):
            await tts.aclose()


async def _send_voice(
    bound: Any,
    gateway: SendGateway,
    session: str,
    chat_id: str,
    data_b64: str,
    pacing: SessionPacing,
) -> None:
    try:
        await gateway.send_voice(session, chat_id, data=data_b64, pacing=pacing)
    except DailyCapExceeded:
        bound.warning("daily cap reached — voice reply suppressed")


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
    "is_voice_fragment",
    "should_reply_voice",
    "is_within_business_hours",
    "run_pipeline",
    "run_tool_loop",
    "should_auto_resume",
    "should_refresh_summary",
    "to_chat_messages",
    "window_history",
]
