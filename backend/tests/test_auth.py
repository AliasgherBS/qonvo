"""Login + /api/me (DESIGN.md §8) — requires a live, MIGRATED Postgres.

Same convention as ``test_rls_postgres.py``: the FastAPI app's ``get_db`` /
``get_system_db`` dependencies are overridden to route through dedicated test
engines built from these two env vars (never through ``app.core.config.settings``,
so the run is deterministic regardless of what that module happened to load).

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5433/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    uv run pytest -m postgres tests/test_auth.py
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.postgres

_APP_URL = os.environ.get("QONVO_TEST_DATABASE_URL")
_SYSTEM_URL = os.environ.get("QONVO_TEST_SYSTEM_DATABASE_URL")

if _APP_URL is None or _SYSTEM_URL is None:
    pytest.skip(
        "QONVO_TEST_DATABASE_URL / QONVO_TEST_SYSTEM_DATABASE_URL not set",
        allow_module_level=True,
    )

from app.api.deps import get_arq, get_db, get_system_db, get_waha, require_tenant  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.tenant import Tenant, TenantUser, User  # noqa: E402
from fastapi import Depends  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

_app_engine = create_async_engine(_APP_URL, poolclass=NullPool)
_system_engine = create_async_engine(_SYSTEM_URL, poolclass=NullPool)
_AppSession = async_sessionmaker(_app_engine, expire_on_commit=False)
_SystemSession = async_sessionmaker(_system_engine, expire_on_commit=False)


@asynccontextmanager
async def _tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with _AppSession() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session


@asynccontextmanager
async def _system_session() -> AsyncIterator[AsyncSession]:
    async with _SystemSession() as session, session.begin():
        yield session


async def _override_get_db(
    tenant_id: uuid.UUID = Depends(require_tenant),
) -> AsyncIterator[AsyncSession]:
    async with _tenant_session(tenant_id) as session:
        yield session


async def _override_get_system_db() -> AsyncIterator[AsyncSession]:
    async with _system_session() as session:
        yield session


@pytest.fixture
async def client():
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_system_db] = _override_get_system_db
    app.dependency_overrides[get_arq] = lambda: AsyncMock()
    app.dependency_overrides[get_waha] = lambda: AsyncMock()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def owner_user():
    """A tenant with one owner user (password: 'correct-password')."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    email = f"owner-{tenant_id.hex[:8]}@example.com"
    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="Auth Test Co", slug=f"auth-test-{tenant_id.hex[:8]}"))
        db.add(
            User(
                id=user_id,
                email=email,
                hashed_password=hash_password("correct-password"),
                full_name="Owner Test",
            )
        )
        await db.flush()
        db.add(TenantUser(tenant_id=tenant_id, user_id=user_id, role=UserRole.owner))
    try:
        yield {"tenant_id": tenant_id, "user_id": user_id, "email": email}
    finally:
        async with _system_session() as db:
            await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def test_login_success(client, owner_user):
    resp = await client.post(
        "/api/auth/login",
        json={"email": owner_user["email"], "password": "correct-password"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "owner"
    assert body["tenant_id"] == str(owner_user["tenant_id"])
    assert body["name"] == "Owner Test"
    assert isinstance(body["access_token"], str) and body["access_token"]


async def test_login_bad_password(client, owner_user):
    resp = await client.post(
        "/api/auth/login",
        json={"email": owner_user["email"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email(client):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "nobody-at-all@example.com", "password": "whatever"},
    )
    assert resp.status_code == 401


async def test_me_returns_profile(client, owner_user):
    login = await client.post(
        "/api/auth/login",
        json={"email": owner_user["email"], "password": "correct-password"},
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == owner_user["email"]
    assert body["role"] == "owner"
    assert body["tenant_id"] == str(owner_user["tenant_id"])
    assert body["tenant_name"] == "Auth Test Co"


async def test_me_without_token_rejected(client):
    resp = await client.get("/api/me")
    assert resp.status_code == 401
