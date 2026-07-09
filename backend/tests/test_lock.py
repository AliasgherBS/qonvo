"""Per-conversation lock behavior (DESIGN.md §5.3)."""

from __future__ import annotations

from app.workers.lock import acquire_conversation_lock, lock_key

CONV = "s1:1@c.us"


async def test_first_acquire_succeeds(fake_redis):
    lock = await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000)
    assert lock.acquired is True
    assert await fake_redis.get(lock_key(CONV)) == lock.token


async def test_second_acquire_blocked_while_held(fake_redis):
    first = await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000)
    second = await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000)
    assert first.acquired is True
    assert second.acquired is False


async def test_release_allows_reacquire(fake_redis):
    first = await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000)
    assert await first.release() is True
    assert await fake_redis.get(lock_key(CONV)) is None
    second = await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000)
    assert second.acquired is True


async def test_release_only_deletes_own_token(fake_redis):
    first = await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000)
    # Simulate the lock being taken over by another worker (different token).
    await fake_redis.set(lock_key(CONV), "someone-elses-token")
    assert await first.release() is False
    assert await fake_redis.get(lock_key(CONV)) == "someone-elses-token"


async def test_context_manager_releases(fake_redis):
    async with await acquire_conversation_lock(fake_redis, CONV, ttl_ms=5000) as lock:
        assert lock.acquired is True
    assert await fake_redis.get(lock_key(CONV)) is None
