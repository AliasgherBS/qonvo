"""Redis SETNX dedupe (DESIGN.md §5.1)."""

from __future__ import annotations

from app.agent.debounce import dedupe_key, is_duplicate


async def test_first_seen_is_not_duplicate(fake_redis):
    assert await is_duplicate(fake_redis, "msg-1", 60) is False


async def test_second_seen_is_duplicate(fake_redis):
    await is_duplicate(fake_redis, "msg-1", 60)
    assert await is_duplicate(fake_redis, "msg-1", 60) is True


async def test_distinct_ids_independent(fake_redis):
    assert await is_duplicate(fake_redis, "msg-1", 60) is False
    assert await is_duplicate(fake_redis, "msg-2", 60) is False


async def test_dedupe_sets_ttl(fake_redis):
    await is_duplicate(fake_redis, "msg-ttl", 60)
    ttl = await fake_redis.ttl(dedupe_key("msg-ttl"))
    assert 0 < ttl <= 60
