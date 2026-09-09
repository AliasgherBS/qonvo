"""Shared test fixtures. Env is seeded *before* app imports so cached settings
pick up valid test values (a real Fernet key, JWT/HMAC secrets)."""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ.setdefault("QONVO_FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("QONVO_JWT_SECRET", "test-jwt-secret-at-least-32-bytes-long-000")
os.environ.setdefault("QONVO_WAHA_HMAC_SECRET", "test-hmac-secret")
os.environ.setdefault("QONVO_DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest  # noqa: E402
from fakeredis import aioredis  # noqa: E402


@pytest.fixture
async def fake_redis():
    client = aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.flushall()
        await client.aclose()


@pytest.fixture(autouse=True)
async def _fresh_redis_client_per_test():
    """Never let a Redis client outlive the event loop that created it.

    ``app.core.redis.get_redis`` caches one client for the process, which is
    right in production: one loop, one pool, for the life of the worker. Under
    pytest-asyncio each test gets its own loop, so the pool's socket ends up
    bound to a loop that has since closed, and the *second* test to touch a
    redis path dies with "got Future attached to a different loop" or "Event
    loop is closed".

    That is why the failure moved when tests were run in a different order --
    it always struck whichever test happened to be second, which reads like
    flakiness and is really shared state.
    """
    import contextlib

    from app.core import redis as redis_module

    redis_module._pool = None
    try:
        yield
    finally:
        stale, redis_module._pool = redis_module._pool, None
        if stale is not None:
            # The loop this belonged to is about to go away; closing is a
            # courtesy and must not be able to fail a passing test.
            with contextlib.suppress(Exception):
                await stale.aclose()


@pytest.fixture(autouse=True)
async def _clear_throttle_counters():
    """Start every test with a clean rate-limit budget.

    The auth endpoints are throttled per IP and per account (``throttle:*`` in
    Redis, with a window measured in minutes). The integration tests all log in
    from the same client address, so the counters carry over between tests and
    across whole runs of the suite -- run it twice inside the window and
    ``test_login_unknown_email`` starts asserting 401 and getting 429, while
    anything that needs a token fails with ``KeyError: 'access_token'``.

    That is a real limiter working correctly on a test suite that looks like a
    brute-force attempt, so the fix belongs in the fixture and not in the
    limiter. Only ``throttle:*`` is touched.
    """
    import contextlib

    from app.core.redis import get_redis

    async def _clear() -> None:
        with contextlib.suppress(Exception):
            client = get_redis()
            keys = [k async for k in client.scan_iter(match="throttle:*", count=500)]
            if keys:
                await client.delete(*keys)

    await _clear()
    yield
    await _clear()
