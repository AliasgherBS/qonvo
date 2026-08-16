"""Team seats: invite → accept → membership, RLS-scoped (DESIGN.md §3, §8).

Requires a live, MIGRATED Postgres (same env as test_admin):
    QONVO_TEST_DATABASE_URL=... QONVO_TEST_SYSTEM_DATABASE_URL=... \\
    uv run pytest -m postgres tests/test_team.py
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

from app.api.deps import get_arq, get_db, get_system_db, require_tenant  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tenant import (  # noqa: E402
    TeamInvitation,
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
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _token(tenant_id: uuid.UUID, role: str) -> str:
    return create_access_token(
        subject=f"{role}@example.com", tenant_id=tenant_id, role=role, is_qonvo_admin=False
    )


@pytest.fixture
async def tenant_cleanup():
    ids: list[uuid.UUID] = []
    emails: list[str] = []
    yield ids, emails
    async with _system_session() as db:
        for tid in ids:
            await db.execute(delete(TeamInvitation).where(TeamInvitation.tenant_id == tid))
            await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tid))
            await db.execute(delete(TenantConfig).where(TenantConfig.tenant_id == tid))
            await db.execute(delete(Tenant).where(Tenant.id == tid))
        for email in emails:
            await db.execute(delete(User).where(User.email == email))


async def _seed_tenant(tenant_id: uuid.UUID) -> None:
    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="Team Co", slug=f"team-{tenant_id.hex[:8]}"))
        await db.flush()
        db.add(TenantConfig(tenant_id=tenant_id))


async def test_invite_then_accept_creates_member(client, tenant_cleanup):
    ids, emails = tenant_cleanup
    tenant_id = uuid.uuid4()
    invitee = f"staff-{tenant_id.hex[:8]}@example.com"
    ids.append(tenant_id)
    emails.append(invitee)
    await _seed_tenant(tenant_id)

    owner_h = {"Authorization": f"Bearer {_token(tenant_id, 'owner')}"}

    # Owner invites.
    resp = await client.post(
        "/api/team/invitations", json={"email": invitee, "role": "staff"}, headers=owner_h
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == invitee

    # Grab the raw token (not returned by the API) to accept.
    async with _tenant_session(tenant_id) as db:
        token = (
            await db.execute(select(TeamInvitation.token).where(TeamInvitation.email == invitee))
        ).scalar_one()

    # Preview is valid + needs a password (no account yet).
    preview = await client.get(f"/api/team/invitations/accept/{token}")
    assert preview.status_code == 200 and preview.json()["valid"] is True
    assert preview.json()["needs_password"] is True

    # Accept with a password → new user + membership + login token.
    accept = await client.post(
        "/api/team/invitations/accept",
        json={"token": token, "password": "hunter2hunter2", "full_name": "Sam Staff"},
    )
    assert accept.status_code == 200
    assert accept.json()["role"] == "staff"

    # The member now shows in the team list.
    team = await client.get("/api/team", headers=owner_h)
    assert team.status_code == 200
    assert invitee in [m["email"] for m in team.json()["members"]]
    # And the invitation is no longer pending.
    assert invitee not in [i["email"] for i in team.json()["invitations"]]

    # Token is single-use: a second accept fails.
    again = await client.post(
        "/api/team/invitations/accept", json={"token": token, "password": "hunter2hunter2"}
    )
    assert again.status_code == 400


async def test_staff_cannot_invite(client, tenant_cleanup):
    ids, _ = tenant_cleanup
    tenant_id = uuid.uuid4()
    ids.append(tenant_id)
    await _seed_tenant(tenant_id)

    staff_h = {"Authorization": f"Bearer {_token(tenant_id, 'staff')}"}
    resp = await client.post(
        "/api/team/invitations", json={"email": "x@example.com"}, headers=staff_h
    )
    assert resp.status_code == 403


async def test_accept_invalid_token_400(client):
    resp = await client.post(
        "/api/team/invitations/accept", json={"token": "nope", "password": "whatever12"}
    )
    assert resp.status_code == 400
