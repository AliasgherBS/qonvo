"""The console's two new reads, end to end (findings F3, A2, A4).

Same environment as ``test_admin`` -- a live, MIGRATED Postgres, and the
integration stack rather than production:

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5443/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5443/qonvo \\
    uv run pytest -m postgres tests/test_admin_console_api.py

``test_admin_plan_change`` pins the plan logic against a fake session, which is
where the reasoning lives. This file is the part that only a database can show:
that ``PUT .../subscription`` really does leave the tenant's *stored*
entitlements matching the catalogue, and that the audit rows the console writes
come back out of ``GET /api/admin/audit`` attributed to the admin who wrote
them.
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
from app.billing.plans import PLANS, TRIAL_PLAN  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.billing import Subscription  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
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


def _admin_headers(subject: str = "ops@qonvo.dev") -> dict[str, str]:
    token = create_access_token(subject=subject, tenant_id=None, role=None, is_qonvo_admin=True)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def tenant():
    """One tenant on the trial plan, with the trial's entitlements in force.

    Created directly rather than through ``POST /tenants`` so the test starts
    from the state a self-serve signup leaves behind, which is the state the
    finding was reported against.
    """
    tenant_id = uuid.uuid4()
    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="QA Salon", slug=f"qa-{tenant_id.hex[:8]}"))
        await db.flush()
        db.add(
            TenantConfig(
                tenant_id=tenant_id,
                entitlements={**PLANS[TRIAL_PLAN].entitlements},
            )
        )
        user = User(
            email=f"owner-{tenant_id.hex[:8]}@example.com",
            hashed_password=hash_password("x" * 16),
            full_name="QA Owner",
        )
        db.add(user)
        await db.flush()
        db.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role=UserRole.owner))
        user_id = user.id

    yield tenant_id

    async with _system_session() as db:
        await db.execute(delete(AuditLog).where(AuditLog.tenant_id == tenant_id))
        await db.execute(delete(Subscription).where(Subscription.tenant_id == tenant_id))
        await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
        await db.execute(delete(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
        await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await db.execute(delete(User).where(User.id == user_id))


# --- F3: the label and the quota have to move together --------------------------- #
async def test_marking_a_tenant_paid_writes_the_catalogue_entitlements(client, tenant):
    """The finding, reproduced against a real database.

    The console's toggle set ``plan: paid`` and left ``monthly_message_quota``
    at the trial's 300. Reading the tenant back has to show the label, the plan
    key and the quota all agreeing.
    """
    resp = await client.put(
        f"/api/admin/tenants/{tenant}/subscription",
        json={"plan_key": "starter", "status": "active"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_key"] == "starter"

    detail = (await client.get(f"/api/admin/tenants/{tenant}", headers=_admin_headers())).json()
    assert detail["plan"] == "paid"
    assert detail["subscription"]["plan_key"] == "starter"
    assert detail["entitlements"] == PLANS["starter"].entitlements
    assert detail["entitlements"]["monthly_message_quota"] == 1_000

    # And the stored row, not just the serialiser.
    async with _system_session() as db:
        stored = (
            await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant))
        ).scalar_one()
        assert stored.entitlements == PLANS["starter"].entitlements


async def test_moving_a_tenant_down_a_tier_lowers_the_quota_too(client, tenant):
    """Entitlements are rewritten, not merged. A downgrade that left the old
    allowance behind is the same invariant failing in the direction that costs
    money rather than the one that annoys a customer."""
    for plan_key in ("scale", "starter"):
        resp = await client.put(
            f"/api/admin/tenants/{tenant}/subscription",
            json={"plan_key": plan_key},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200, resp.text

    detail = (await client.get(f"/api/admin/tenants/{tenant}", headers=_admin_headers())).json()
    assert detail["entitlements"] == PLANS["starter"].entitlements


async def test_the_patch_route_refuses_the_plan_label(client, tenant):
    """The old "Mark as paid" request. It has to 400 rather than half-succeed."""
    resp = await client.patch(
        f"/api/admin/tenants/{tenant}",
        json={"plan": "paid"},
        headers=_admin_headers(),
    )

    assert resp.status_code == 400
    assert "subscription" in resp.json()["detail"]

    detail = (await client.get(f"/api/admin/tenants/{tenant}", headers=_admin_headers())).json()
    assert detail["plan"] == "trial"
    assert detail["entitlements"]["monthly_message_quota"] == 300


async def test_the_trial_end_date_is_settable(client, tenant):
    """Finding A4: the field worked and nothing set it."""
    resp = await client.patch(
        f"/api/admin/tenants/{tenant}",
        json={"trial_ends_at": "2026-12-01T00:00:00Z"},
        headers=_admin_headers(),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["trial_ends_at"].startswith("2026-12-01")


async def test_the_tenant_list_carries_the_plan_key(client, tenant):
    """"Paid" is two values over a four-tier catalogue, so the list cannot
    answer "who is on Growth" without this."""
    await client.put(
        f"/api/admin/tenants/{tenant}/subscription",
        json={"plan_key": "growth"},
        headers=_admin_headers(),
    )

    rows = (await client.get("/api/admin/tenants", headers=_admin_headers())).json()
    row = next(r for r in rows if r["id"] == str(tenant))

    assert row["plan_key"] == "growth"
    assert row["plan"] == "paid"


async def test_the_plan_catalogue_is_served_to_the_picker(client):
    resp = await client.get("/api/admin/plans", headers=_admin_headers())

    assert resp.status_code == 200
    assert [p["key"] for p in resp.json()] == list(PLANS)


# --- A2: the trail is readable --------------------------------------------------- #
async def test_the_console_can_read_back_what_it_just_did(client, tenant):
    """Suspend a tenant, then ask who suspended it. That question needed psql."""
    await client.patch(
        f"/api/admin/tenants/{tenant}",
        json={"status": "suspended"},
        headers=_admin_headers("hassan@qonvo.dev"),
    )

    body = (
        await client.get(f"/api/admin/audit?tenant_id={tenant}", headers=_admin_headers())
    ).json()

    assert body["total"] >= 1
    row = body["items"][0]
    assert row["action"] == "tenant.update"
    assert row["actor_email"] == "hassan@qonvo.dev"
    assert row["actor_role"] == "qonvo_admin"
    assert row["tenant_name"] == "QA Salon"
    # The changed field names ride along in meta; the actor keys do not, because
    # they are their own columns.
    assert row["meta"]["fields"] == ["status"]
    assert "actor_email" not in row["meta"]


async def test_the_trail_is_newest_first(client, tenant):
    for status in ("suspended", "active"):
        await client.patch(
            f"/api/admin/tenants/{tenant}",
            json={"status": status},
            headers=_admin_headers(),
        )
    await client.put(
        f"/api/admin/tenants/{tenant}/subscription",
        json={"plan_key": "starter"},
        headers=_admin_headers(),
    )

    body = (
        await client.get(f"/api/admin/audit?tenant_id={tenant}", headers=_admin_headers())
    ).json()

    assert body["items"][0]["action"] == "tenant.subscription.set"


async def test_the_trail_filters_by_actor_and_by_action(client, tenant):
    await client.patch(
        f"/api/admin/tenants/{tenant}",
        json={"status": "suspended"},
        headers=_admin_headers("aisha@qonvo.dev"),
    )
    await client.post(
        f"/api/admin/tenants/{tenant}/impersonate", headers=_admin_headers("bilal@qonvo.dev")
    )

    by_actor = (
        await client.get(
            f"/api/admin/audit?tenant_id={tenant}&actor=aisha", headers=_admin_headers()
        )
    ).json()
    assert {r["action"] for r in by_actor["items"]} == {"tenant.update"}

    by_action = (
        await client.get(
            f"/api/admin/audit?tenant_id={tenant}&action=impersonate", headers=_admin_headers()
        )
    ).json()
    assert {r["actor_email"] for r in by_action["items"]} == {"bilal@qonvo.dev"}


async def test_the_trail_pages(client, tenant):
    for status in ("suspended", "active", "suspended"):
        await client.patch(
            f"/api/admin/tenants/{tenant}",
            json={"status": status},
            headers=_admin_headers(),
        )

    first = (
        await client.get(
            f"/api/admin/audit?tenant_id={tenant}&limit=2", headers=_admin_headers()
        )
    ).json()
    second = (
        await client.get(
            f"/api/admin/audit?tenant_id={tenant}&limit=2&offset=2", headers=_admin_headers()
        )
    ).json()

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    # No row appears on both pages: the sort has a stable tiebreak.
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}


async def test_the_trail_is_admin_only(client, tenant):
    owner = create_access_token(
        subject="owner@example.com", tenant_id=tenant, role="owner", is_qonvo_admin=False
    )

    resp = await client.get(
        "/api/admin/audit", headers={"Authorization": f"Bearer {owner}"}
    )

    assert resp.status_code == 403
