"""Debounce window coalescing (DESIGN.md §5.2)."""

from __future__ import annotations

from app.agent.debounce import add_fragment, close_window
from app.workers.pipeline import InboundFragment, coalesce_fragments

SESSION = "s1"
CHAT = "1@c.us"


def _frag(i: int) -> dict:
    return {"message_id": f"m{i}", "type": "text", "body": f"part {i}"}


async def test_generation_increments(fake_redis):
    g1 = await add_fragment(fake_redis, SESSION, CHAT, _frag(1), window_seconds=5)
    g2 = await add_fragment(fake_redis, SESSION, CHAT, _frag(2), window_seconds=5)
    assert g1 == 1
    assert g2 == 2


async def test_stale_generation_is_noop(fake_redis):
    await add_fragment(fake_redis, SESSION, CHAT, _frag(1), window_seconds=5)
    gen2 = await add_fragment(fake_redis, SESSION, CHAT, _frag(2), window_seconds=5)
    # The first window (generation 1) fired late — must be a no-op.
    assert await close_window(fake_redis, SESSION, CHAT, 1) is None
    # The current generation drains everything as one coalesced turn.
    fragments = await close_window(fake_redis, SESSION, CHAT, gen2)
    assert fragments is not None
    assert [f["message_id"] for f in fragments] == ["m1", "m2"]


async def test_close_window_coalesces_in_order(fake_redis):
    for i in range(1, 4):
        gen = await add_fragment(fake_redis, SESSION, CHAT, _frag(i), window_seconds=5)
    fragments = await close_window(fake_redis, SESSION, CHAT, gen)
    parsed = [InboundFragment(**f) for f in fragments]
    assert coalesce_fragments(parsed) == "part 1\npart 2\npart 3"


async def test_buffer_cleared_after_close(fake_redis):
    gen = await add_fragment(fake_redis, SESSION, CHAT, _frag(1), window_seconds=5)
    await close_window(fake_redis, SESSION, CHAT, gen)
    # A subsequent stale close finds nothing and returns None.
    assert await close_window(fake_redis, SESSION, CHAT, gen) is None
