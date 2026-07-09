"""Internal ops console: tenant lifecycle, fleet, usage, RLS scoping on admin
routes (DESIGN.md §9) — requires a live, MIGRATED Postgres.

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5433/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    uv run pytest -m postgres tests/test_admin.py
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
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
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import SessionStatus  # noqa: E402
from app.models.ops import UsageCounter  # noqa: E402
from app.models.tenant import AuditLog, Tenant, TenantConfig, TenantUser, User  # noqa: E402
from app.models.whatsapp import WhatsAppSession  # noqa: E402
from app.services.auth import create_access_token  # noqa: E402
from fastapi import Depends  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
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
def mock_waha():
    waha = AsyncMock()
    waha.get_session.return_value = {"status": "WORKING"}
    return waha


@pytest.fixture
async def client(mock_waha):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_system_db] = _override_get_system_db
    app.dependency_overrides[get_arq] = lambda: AsyncMock()
    app.dependency_overrides[get_waha] = lambda: mock_waha
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _admin_token() -> str:
    return create_access_token(
        subject="admin@example.com", tenant_id=None, role=None, is_qonvo_admin=True
    )


def _owner_token(tenant_id: uuid.UUID) -> str:
    return create_access_token(
        subject="owner@example.com", tenant_id=tenant_id, role="owner", is_qonvo_admin=False
    )


@pytest.fixture
async def created_tenant_cleanup():
    """Tracks tenant ids created during a test so teardown can sweep them."""
    tenant_ids: list[uuid.UUID] = []
    yield tenant_ids
    async with _system_session() as db:
        for tid in tenant_ids:
            await db.execute(delete(AuditLog).where(AuditLog.tenant_id == tid))
            await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tid))
            await db.execute(delete(TenantConfig).where(TenantConfig.tenant_id == tid))
            await db.execute(delete(WhatsAppSession).where(WhatsAppSession.tenant_id == tid))
            await db.execute(delete(UsageCounter).where(UsageCounter.tenant_id == tid))
            await db.execute(delete(Tenant).where(Tenant.id == tid))
        await db.execute(delete(User).where(User.email == "new-owner@example.com"))


async def test_create_tenant_requires_admin(client):
    resp = await client.post(
        "/api/admin/tenants",
        json={"name": "Acme", "slug": "acme-x", "owner_email": "owner@example.com"},
    )
    assert resp.status_code == 401


async def test_create_tenant_rejects_non_admin(client):
    headers = {"Authorization": f"Bearer {_owner_token(uuid.uuid4())}"}
    resp = await client.post(
        "/api/admin/tenants",
        json={"name": "Acme", "slug": "acme-y", "owner_email": "owner@example.com"},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_create_tenant_provisions_user_and_config(client, created_tenant_cleanup):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = await client.post(
        "/api/admin/tenants",
        json={
            "name": "New Biz",
            "slug": f"new-biz-{uuid.uuid4().hex[:8]}",
            "owner_email": "new-owner@example.com",
            "owner_name": "New Owner",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    tenant_id = uuid.UUID(body["id"])
    created_tenant_cleanup.append(tenant_id)
    assert body["owner_email"] == "new-owner@example.com"
    assert isinstance(body["temp_password"], str) and body["temp_password"]

    async with _system_session() as db:
        config = (
            await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
        ).scalar_one_or_none()
        assert config is not None

        membership = (
            await db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant_id))
        ).scalar_one_or_none()
        assert membership is not None
        assert membership.role.value == "owner"

        user = (
            await db.execute(select(User).where(User.email == "new-owner@example.com"))
        ).scalar_one_or_none()
        assert user is not None
        assert user.full_name == "New Owner"

        audit = (
            await db.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_id))
        ).scalars().all()
        assert any(a.action == "tenant.create" for a in audit)


async def test_create_tenant_duplicate_slug_conflicts(client, created_tenant_cleanup):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    slug = f"dupe-{uuid.uuid4().hex[:8]}"
    first = await client.post(
        "/api/admin/tenants",
        json={"name": "First", "slug": slug, "owner_email": "dupe-owner@example.com"},
        headers=headers,
    )
    created_tenant_cleanup.append(uuid.UUID(first.json()["id"]))

    second = await client.post(
        "/api/admin/tenants",
        json={"name": "Second", "slug": slug, "owner_email": "dupe-owner-2@example.com"},
        headers=headers,
    )
    assert second.status_code == 409
    async with _system_session() as db:
        await db.execute(delete(User).where(User.email == "dupe-owner@example.com"))


async def test_get_tenant_and_update_config(client, created_tenant_cleanup):
    headers = {"Authorization": f"Bearer {_admin_token()}"}
    create = await client.post(
        "/api/admin/tenants",
        json={
            "name": "Config Co",
            "slug": f"config-co-{uuid.uuid4().hex[:8]}",
            "owner_email": "config-owner@example.com",
        },
        headers=headers,
    )
    tenant_id = create.json()["id"]
    created_tenant_cleanup.append(uuid.UUID(tenant_id))

    got = await client.get(f"/api/admin/tenants/{tenant_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["config"] is not None

    updated = await client.put(
        f"/api/admin/tenants/{tenant_id}/config",
        json={"business_name": "Config Co Ltd", "owner_alert_number": "923001234567"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["business_name"] == "Config Co Ltd"
    assert updated.json()["owner_alert_number"] == "923001234567"

    async with _system_session() as db:
        await db.execute(delete(User).where(User.email == "config-owner@example.com"))


async def test_fleet_lists_sessions_with_live_status(client, created_tenant_cleanup, mock_waha):
    tenant_id = uuid.uuid4()
    session_name = f"fleet-test-{tenant_id.hex[:8]}"
    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="Fleet Co", slug=f"fleet-{tenant_id.hex[:8]}"))
        await db.flush()
        db.add(
            WhatsAppSession(
                tenant_id=tenant_id,
                session_name=session_name,
                status=SessionStatus.working,
            )
        )
    created_tenant_cleanup.append(tenant_id)

    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = await client.get("/api/admin/fleet", headers=headers)
    assert resp.status_code == 200
    matches = [s for s in resp.json() if s["session_name"] == session_name]
    assert len(matches) == 1
    assert matches[0]["live_status"] == "WORKING"
    mock_waha.get_session.assert_any_call(session_name)


async def test_usage_rollup_per_tenant(client, created_tenant_cleanup):
    tenant_id = uuid.uuid4()
    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="Usage Co", slug=f"usage-{tenant_id.hex[:8]}"))
        await db.flush()
        db.add(
            UsageCounter(
                tenant_id=tenant_id,
                day=date(2026, 6, 15),
                messages_in=10,
                messages_out=8,
                tokens=1000,
                cost=1.5,
            )
        )
    created_tenant_cleanup.append(tenant_id)

    headers = {"Authorization": f"Bearer {_admin_token()}"}
    resp = await client.get("/api/admin/usage?month=2026-06", headers=headers)
    assert resp.status_code == 200
    rows = [r for r in resp.json() if r["tenant_id"] == str(tenant_id)]
    assert len(rows) == 1
    assert rows[0]["messages_in"] == 10
    assert rows[0]["messages_out"] == 8

    other_month = await client.get("/api/admin/usage?month=2026-01", headers=headers)
    assert all(r["tenant_id"] != str(tenant_id) for r in other_month.json())


async def test_admin_routes_scoped_from_regular_tenant_token(client):
    headers = {"Authorization": f"Bearer {_owner_token(uuid.uuid4())}"}
    resp = await client.get("/api/admin/tenants", headers=headers)
    assert resp.status_code == 403
    resp = await client.get("/api/admin/fleet", headers=headers)
    assert resp.status_code == 403
    resp = await client.get("/api/admin/usage", headers=headers)
    assert resp.status_code == 403
