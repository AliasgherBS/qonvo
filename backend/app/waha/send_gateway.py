"""Single outbound gateway enforcing pacing, ordering, and ban-avoidance.

Every outbound WhatsApp message — bot replies, human-via-dashboard, reminders —
flows through here (DESIGN.md §5.6). No feature code calls the WAHA client's send
methods directly.

Pacing per session:
- **Token bucket** in Redis: burst of N, refilling at 1 token per jittered
  ``[min, max]`` seconds → default 1 msg / 3–8 s.
- **Daily cap** from ``whatsapp_sessions.daily_cap``, reduced by the new-number
  warm-up schedule (week 1 → 50/day, week 2 → 150/day).
- **Human-like sequence**: ``sendSeen`` → ``startTyping`` → delay ∝ reply length
  → send → ``stopTyping``.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import logger
from app.waha.client import WahaClient

# Warm-up stage → daily-cap ceiling (DESIGN.md §5.6). Stage 0 = no warm-up limit.
WARMUP_STAGE_CAPS: dict[int, int] = {1: 50, 2: 150}


def own_send_key(message_id: str) -> str:
    return f"waha:ownsend:{message_id}"


def own_send_fingerprint(source: object) -> str | None:
    """Stable per-message id-hash for recognizing our own sends across engines.

    WAHA echoes every send back as a ``fromMe`` ``message.any``; we must match it
    against what we sent so the bot doesn't mistake its own reply for the owner
    replying (which triggers implicit takeover and silences the bot, §5.5).

    Engines disagree on both the id shape *and* the JID suffix — NOWEB sends to
    ``…@s.whatsapp.net`` but echoes the copy as ``…@c.us``/``@lid`` — so the full
    serialized id never round-trips. The bare id hash is identical on the send
    response and its echo, so we key on that:

    - NOWEB send result:  ``{"key": {"id": "3EB0…"}}``            → ``3EB0…``
    - WEBJS send result:  ``{"id": {"_serialized": "true_…_H"}}`` → ``H``
    - webhook echo id:    ``"true_29918…@lid_3EB0…"``             → ``3EB0…``
    """
    serialized: str | None
    if isinstance(source, str):
        serialized = source or None
    elif isinstance(source, dict):
        key = source.get("key")
        raw = source.get("id")
        if isinstance(key, dict) and isinstance(key.get("id"), str):
            serialized = key["id"]  # NOWEB send response
        elif isinstance(raw, str):
            serialized = raw
        elif isinstance(raw, dict) and isinstance(raw.get("_serialized"), str):
            serialized = raw["_serialized"]  # WEBJS send response
        elif isinstance(source.get("_serialized"), str):
            serialized = source["_serialized"]
        else:
            serialized = None
    else:
        serialized = None
    if not serialized:
        return None
    # Serialized ids are "<fromMe>_<jid>_<hash>"; the bare hash is the tail and
    # is engine/JID-agnostic (a bare id with no "_" is returned unchanged).
    return serialized.rsplit("_", 1)[-1]


async def is_own_send(client: redis.Redis, message_id: str | None) -> bool:
    """True when this message id was sent by our own gateway (§5.5)."""
    if not message_id:
        return False
    return bool(await client.exists(own_send_key(message_id)))


class DailyCapExceeded(Exception):
    """Raised when the session's daily send cap has been reached."""


# --------------------------------------------------------------------------- #
# Pure pacing math (unit-tested without Redis/network)
# --------------------------------------------------------------------------- #
def typing_delay_seconds(
    text: str,
    *,
    per_char: float | None = None,
    max_seconds: float | None = None,
) -> float:
    """Length-proportional typing delay, capped."""
    per_char = per_char if per_char is not None else settings.typing_seconds_per_char
    max_seconds = max_seconds if max_seconds is not None else settings.typing_max_seconds
    return min(len(text) * per_char, max_seconds)


def effective_daily_cap(warmup_stage: int, daily_cap: int) -> int:
    """Apply the warm-up ceiling, taking the stricter of the two limits."""
    warmup_cap = WARMUP_STAGE_CAPS.get(warmup_stage)
    if warmup_cap is None:
        return daily_cap
    return min(daily_cap, warmup_cap)


def token_bucket_wait(
    tokens: float,
    last_ts: float,
    now: float,
    *,
    capacity: int,
    refill_seconds: float,
) -> tuple[float, float]:
    """Advance a token bucket and return ``(wait_seconds, new_token_count)``.

    ``refill_seconds`` is the (jittered) interval that yields one token. The
    returned token count is *after* consuming one token; ``wait_seconds`` is how
    long the caller must sleep before the send is allowed.
    """
    refill_rate = 1.0 / refill_seconds
    elapsed = max(0.0, now - last_ts)
    tokens = min(float(capacity), tokens + elapsed * refill_rate)
    if tokens >= 1.0:
        return 0.0, tokens - 1.0
    wait = (1.0 - tokens) / refill_rate
    return wait, 0.0


# --------------------------------------------------------------------------- #
# Send gateway
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SessionPacing:
    daily_cap: int = 500
    warmup_stage: int = 0
    burst: int | None = None
    min_delay: float | None = None
    max_delay: float | None = None


def pacing_for_session(session_row: Any) -> SessionPacing:
    """Build pacing from a ``WhatsAppSession`` row.

    Every send path must go through this rather than constructing a bare
    ``SessionPacing()``: the dataclass defaults are a generous 500/day with no
    warm-up, so a default-constructed pacing silently ignores whatever the
    session was actually configured for.
    """
    return SessionPacing(
        daily_cap=session_row.daily_cap,
        warmup_stage=session_row.warmup_stage,
    )


class SendGateway:
    """Serialized, paced sender for one WAHA deployment."""

    def __init__(
        self,
        waha: WahaClient,
        redis_client: redis.Redis,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.monotonic,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._waha = waha
        self._redis = redis_client
        self._sleep = sleep
        self._now = now
        self._jitter = jitter

    async def _check_daily_cap(self, session: str, pacing: SessionPacing) -> None:
        cap = effective_daily_cap(pacing.warmup_stage, pacing.daily_cap)
        day = datetime.now(UTC).strftime("%Y%m%d")
        key = f"waha:daily:{session}:{day}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 172_800)  # 48h, covers the UTC day
        if count > cap:
            # Roll back the increment we just made for a rejected send.
            await self._redis.decr(key)
            raise DailyCapExceeded(f"session {session} hit daily cap {cap}")

    async def _await_slot(self, session: str, pacing: SessionPacing) -> None:
        burst = pacing.burst if pacing.burst is not None else settings.send_burst
        min_delay = (
            pacing.min_delay if pacing.min_delay is not None else settings.send_min_delay_seconds
        )
        max_delay = (
            pacing.max_delay if pacing.max_delay is not None else settings.send_max_delay_seconds
        )
        refill_seconds = self._jitter(min_delay, max_delay)

        key = f"waha:bucket:{session}"
        now = self._now()
        raw = await self._redis.hgetall(key)
        tokens = float(raw.get("tokens", burst)) if raw else float(burst)
        last_ts = float(raw.get("ts", now)) if raw else now

        wait, new_tokens = token_bucket_wait(
            tokens, last_ts, now, capacity=burst, refill_seconds=refill_seconds
        )
        await self._redis.hset(key, mapping={"tokens": new_tokens, "ts": now + wait})
        await self._redis.expire(key, 3_600)
        if wait > 0:
            await self._sleep(wait)

    async def send_text(
        self,
        session: str,
        chat_id: str,
        text: str,
        *,
        pacing: SessionPacing,
        reply_to: str | None = None,
    ) -> dict:
        """Human-like paced text send: seen → typing → delay → send → stop."""
        await self._check_daily_cap(session, pacing)
        await self._await_slot(session, pacing)

        await self._waha.send_seen(session, chat_id)
        await self._waha.start_typing(session, chat_id)
        try:
            await self._sleep(typing_delay_seconds(text))
            result = await self._waha.send_text(session, chat_id, text, reply_to=reply_to)
        finally:
            await self._waha.stop_typing(session, chat_id)
        await self._record_own_send(result)
        logger.bind(session=session, chat_id=chat_id).info("sent text via gateway")
        return result

    async def _record_own_send(self, result: dict) -> None:
        """Mark a message id as sent-by-us (24h TTL).

        WAHA echoes our own sends back as ``message.any`` with ``fromMe=true``
        — indistinguishable from the owner replying manually from the linked
        phone. Without this marker the bot's own reply triggers implicit
        takeover and the bot silences itself (caught live, §5.5).
        """
        fingerprint = own_send_fingerprint(result)
        if fingerprint:
            await self._redis.set(own_send_key(fingerprint), "1", ex=86_400)

    async def send_voice(
        self,
        session: str,
        chat_id: str,
        *,
        url: str | None = None,
        data: str | None = None,
        pacing: SessionPacing,
    ) -> dict:
        await self._check_daily_cap(session, pacing)
        await self._await_slot(session, pacing)

        await self._waha.send_seen(session, chat_id)
        await self._waha.start_typing(session, chat_id)
        try:
            result = await self._waha.send_voice(session, chat_id, url=url, data=data)
        finally:
            await self._waha.stop_typing(session, chat_id)
        await self._record_own_send(result)
        logger.bind(session=session, chat_id=chat_id).info("sent voice via gateway")
        return result


__all__ = [
    "DailyCapExceeded",
    "SendGateway",
    "SessionPacing",
    "effective_daily_cap",
    "pacing_for_session",
    "token_bucket_wait",
    "typing_delay_seconds",
]
