"""Dedupe + debounce/burst aggregation for inbound messages (DESIGN.md §5.1–5.2).

Redis key layout, per ``(session, chatId)``:
- ``waha:msg:{message_id}``        SETNX + TTL — cross-restart dedupe cache.
- ``waha:buf:{session}:{chatId}``  list of buffered fragment payloads (JSON).
- ``waha:bufgen:{session}:{chatId}`` monotonically increasing generation token.

Debounce uses a *generation* token instead of a live timer: each fragment bumps
the generation and schedules a delayed ``close_window`` for that generation. Only
the delayed job whose generation still matches wins — every earlier one is a
no-op, which is exactly a 5 s sliding window that resets on each fragment.
"""

from __future__ import annotations

import json

import redis.asyncio as redis


def dedupe_key(message_id: str) -> str:
    return f"waha:msg:{message_id}"


def buffer_key(session: str, chat_id: str) -> str:
    return f"waha:buf:{session}:{chat_id}"


def generation_key(session: str, chat_id: str) -> str:
    return f"waha:bufgen:{session}:{chat_id}"


async def is_duplicate(client: redis.Redis, message_id: str, ttl_seconds: int) -> bool:
    """Return ``True`` if this message id was already seen (SETNX-based).

    The first caller for a given id sets the marker and gets ``False``; every
    subsequent caller within the TTL gets ``True``. Backed by the
    ``messages.wa_message_id`` unique constraint for restart safety.
    """
    was_set = await client.set(dedupe_key(message_id), "1", nx=True, ex=ttl_seconds)
    return not bool(was_set)


async def is_rate_limited(
    client: redis.Redis, session: str, chat_id: str, *, limit: int, window_seconds: int
) -> bool:
    """Fixed-window per-(session, chat) inbound rate limit.

    Bounds LLM spend from a single customer hammering the number — the debounce
    window coalesces bursts, but nothing else caps sustained inbound. Returns
    True once more than ``limit`` messages arrive from the same chat inside
    ``window_seconds`` (those are dropped before they reach the pipeline).
    """
    key = f"waha:rl:{session}:{chat_id}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, window_seconds)
    return count > limit


async def add_fragment(
    client: redis.Redis,
    session: str,
    chat_id: str,
    fragment: dict,
    *,
    window_seconds: float,
) -> int:
    """Append a fragment to the buffer and return the new generation token."""
    bkey = buffer_key(session, chat_id)
    await client.rpush(bkey, json.dumps(fragment))
    # Keep the buffer from leaking if a close_window job is ever lost.
    await client.expire(bkey, int(window_seconds) + 60)
    gen = await client.incr(generation_key(session, chat_id))
    await client.expire(generation_key(session, chat_id), int(window_seconds) + 60)
    return gen


async def close_window(
    client: redis.Redis,
    session: str,
    chat_id: str,
    generation: int,
) -> list[dict] | None:
    """Coalesce and drain the buffer iff ``generation`` is still current.

    Returns the buffered fragments in arrival order, or ``None`` when a newer
    fragment has reset the window (this call should be a no-op).
    """
    current = await client.get(generation_key(session, chat_id))
    if current is None or int(current) != generation:
        return None

    bkey = buffer_key(session, chat_id)
    raw = await client.lrange(bkey, 0, -1)
    async with client.pipeline(transaction=True) as pipe:
        pipe.delete(bkey)
        pipe.delete(generation_key(session, chat_id))
        await pipe.execute()
    return [json.loads(item) for item in raw]


__all__ = [
    "add_fragment",
    "buffer_key",
    "close_window",
    "dedupe_key",
    "generation_key",
    "is_duplicate",
]
