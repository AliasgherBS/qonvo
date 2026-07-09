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
