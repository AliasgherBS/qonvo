"""Billing endpoints end to end (billing design §3.5).

Requires a live, MIGRATED Postgres (same env as test_admin):
    QONVO_TEST_DATABASE_URL=... QONVO_TEST_SYSTEM_DATABASE_URL=... \\
    uv run pytest -m postgres tests/test_billing_api.py
"""

from __future__ import annotations

import datetime as dt
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

from app.api.deps import get_arq, get_db, get_system_db, require_tenant  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.billing import BillingEvent, Subscription  # noqa: E402
from app.models.tenant import (  # noqa: E402
    AuditLog,
    Tenant,
    TenantConfig,
    TenantUser,
    User,
)
from app.services.auth import create_access_token  # noqa: E402
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
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _owner(tenant_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        subject="owner@example.com", tenant_id=tenant_id, role="owner", is_qonvo_admin=False
    )
    return {"Authorization": f"Bearer {token}"}


def _admin(tenant_id: uuid.UUID) -> dict[str, str]:
    token = create_access_token(
        subject="admin@example.com", tenant_id=tenant_id, role="owner", is_qonvo_admin=True
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def tenant_cleanup():
    ids: list[uuid.UUID] = []
    yield ids
    async with _system_session() as db:
        for tid in ids:
            await db.execute(delete(AuditLog).where(AuditLog.tenant_id == tid))
            await db.execute(delete(BillingEvent).where(BillingEvent.tenant_id == tid))
            await db.execute(delete(Subscription).where(Subscription.tenant_id == tid))
            await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tid))
            await db.execute(delete(TenantConfig).where(TenantConfig.tenant_id == tid))
            await db.execute(delete(Tenant).where(Tenant.id == tid))


async def _seed_tenant(tenant_id: uuid.UUID, *, plan: str = "trial", trial_days: int = 5) -> None:
    async with _system_session() as db:
        db.add(
            Tenant(
                id=tenant_id,
                name="Billing Co",
                slug=f"bill-{tenant_id.hex[:8]}",
                plan=plan,
                trial_ends_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=trial_days),
            )
        )
        await db.flush()
        db.add(TenantConfig(tenant_id=tenant_id, entitlements={"monthly_message_quota": 300}))


# --- owner surface ----------------------------------------------------------- #
async def test_billing_status_reports_a_live_trial(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    body = (await client.get("/api/billing", headers=_owner(tenant_id))).json()

    assert body["plan"] == "trial"
    assert body["expired"] is False
    assert body["blocked_reason"] is None
    assert body["subscription"] is None
    assert body["days_left"] == 5


async def test_plans_are_listed_without_prices(client, tenant_cleanup):
    """Prices live with the payment provider and must never leak into the API."""
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    plans = (await client.get("/api/billing/plans", headers=_owner(tenant_id))).json()

    assert [p["key"] for p in plans] == ["trial", "starter", "growth", "scale"]
    assert all("price" not in p for p in plans)


async def test_checkout_with_no_gateway_returns_instructions(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    resp = await client.post(
        "/api/billing/checkout", json={"plan_key": "growth"}, headers=_owner(tenant_id)
    )

    assert resp.status_code == 200
    assert resp.json()["url"] is None
    assert resp.json()["instructions"]


async def test_checkout_rejects_an_unknown_plan(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    resp = await client.post(
        "/api/billing/checkout", json={"plan_key": "unlimited"}, headers=_owner(tenant_id)
    )

    assert resp.status_code == 400


# --- admin marking a tenant paid --------------------------------------------- #
async def test_admin_can_put_a_tenant_on_a_plan(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    resp = await client.put(
        f"/api/admin/tenants/{tenant_id}/subscription",
        json={"plan_key": "growth", "status": "active"},
        headers=_admin(tenant_id),
    )
    assert resp.status_code == 200

    body = (await client.get("/api/billing", headers=_owner(tenant_id))).json()
    assert body["subscription"]["plan_key"] == "growth"
    assert body["plan"] == "paid"
    assert body["expired"] is False


async def test_setting_a_plan_rewrites_entitlements_from_the_catalogue(client, tenant_cleanup):
    """The whole point of a catalogue: a plan change cannot leave a stale quota."""
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    await client.put(
        f"/api/admin/tenants/{tenant_id}/subscription",
        json={"plan_key": "scale", "status": "active"},
        headers=_admin(tenant_id),
    )

    body = (await client.get("/api/billing", headers=_owner(tenant_id))).json()
    assert body["entitlements"]["monthly_message_quota"] == 20_000
    assert body["entitlements"]["seats"] == 15


async def test_an_expired_cancellation_blocks_service(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    await client.put(
        f"/api/admin/tenants/{tenant_id}/subscription",
        json={
            "plan_key": "starter",
            "status": "canceled",
            "current_period_end": (
                dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
            ).isoformat(),
        },
        headers=_admin(tenant_id),
    )

    body = (await client.get("/api/billing", headers=_owner(tenant_id))).json()
    assert body["expired"] is True
    assert body["blocked_reason"] == "canceled"


async def test_admin_rejects_an_unknown_plan(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    resp = await client.put(
        f"/api/admin/tenants/{tenant_id}/subscription",
        json={"plan_key": "bespoke", "status": "active"},
        headers=_admin(tenant_id),
    )
    assert resp.status_code == 400


async def test_an_owner_cannot_set_their_own_subscription(client, tenant_cleanup):
    """Otherwise upgrading is free."""
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    resp = await client.put(
        f"/api/admin/tenants/{tenant_id}/subscription",
        json={"plan_key": "scale", "status": "active"},
        headers=_owner(tenant_id),
    )
    assert resp.status_code == 403


# --- seats ------------------------------------------------------------------- #
async def test_inviting_past_the_seat_limit_is_refused(client, tenant_cleanup):
    tenant_id = uuid.uuid4()
    tenant_cleanup.append(tenant_id)
    await _seed_tenant(tenant_id)

    # Starter grants 2 seats. Seat one with the owner, claim the second by invite.
    async with _system_session() as db:
        user = User(email=f"owner-{tenant_id.hex[:8]}@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        db.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role="owner"))
    await client.put(
        f"/api/admin/tenants/{tenant_id}/subscription",
        json={"plan_key": "starter", "status": "active"},
        headers=_admin(tenant_id),
    )

    first = await client.post(
        "/api/team/invitations",
        json={"email": f"a-{tenant_id.hex[:8]}@example.com", "role": "staff"},
        headers=_owner(tenant_id),
    )
    second = await client.post(
        "/api/team/invitations",
        json={"email": f"b-{tenant_id.hex[:8]}@example.com", "role": "staff"},
        headers=_owner(tenant_id),
    )

    assert first.status_code == 201
    assert second.status_code == 402

    async with _system_session() as db:
        await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
        await db.execute(
            delete(User).where(User.email == f"owner-{tenant_id.hex[:8]}@example.com")
        )
