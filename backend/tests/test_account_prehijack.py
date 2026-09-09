"""The pre-hijacking scenario, end to end (teardown X2) — needs a live Postgres.

Same convention as ``test_auth.py``: the app's db dependencies are overridden
onto dedicated test engines built from these env vars.

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5443/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5443/qonvo \\
    uv run pytest -m postgres tests/test_account_prehijack.py

The unit tests in ``test_email_verification.py`` cover the token. This file
covers the decision the token exists to enable, which lives in a route and
cannot be reached without a database: whether ``POST /api/auth/google`` hands a
stranger's Google identity the keys to a row somebody else created.

Google's id_token verification is stubbed. That is the point of the stub rather
than a shortcut: the attack assumes Google behaves perfectly and asserts an
address it really has verified. What is under test is what *we* do with a
correct assertion.
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

from app.api import auth as auth_api  # noqa: E402
from app.api.deps import get_arq, get_db, get_system_db, get_waha, require_tenant  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.tenant import Tenant, TenantUser, User  # noqa: E402
from app.services.auth import create_password_reset_token  # noqa: E402
from app.services.google_identity import GoogleIdentity  # noqa: E402
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

PASSWORD = "the-attackers-password"


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
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def as_google(monkeypatch):
    """Make Google assert an address, exactly as it would for its real owner."""

    def install(email: str, *, name: str | None = "Real Owner"):
        async def fake(id_token: str) -> GoogleIdentity:
            return GoogleIdentity(
                subject=f"google-sub-{email}",
                email=email,
                full_name=name,
                email_verified=True,
            )

        monkeypatch.setattr(auth_api, "verify_google_id_token", fake)

    return install


@pytest.fixture
async def account():
    """A tenant whose owner has a password. Verification state is set per test."""
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    email = f"owner-{tenant_id.hex[:8]}@theclinic.example"

    async def make(*, email_verified: bool, with_password: bool = True):
        async with _system_session() as db:
            db.add(
                Tenant(
                    id=tenant_id,
                    name="The Clinic",
                    slug=f"clinic-{tenant_id.hex[:8]}",
                )
            )
            db.add(
                User(
                    id=user_id,
                    email=email,
                    hashed_password=hash_password(PASSWORD) if with_password else None,
                    full_name="Squatter",
                    email_verified=email_verified,
                )
            )
            await db.flush()
            db.add(TenantUser(tenant_id=tenant_id, user_id=user_id, role=UserRole.owner))
        return {"tenant_id": tenant_id, "user_id": user_id, "email": email}

    try:
        yield make
    finally:
        async with _system_session() as db:
            await db.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def _verified(email: str) -> bool:
    async with _system_session() as db:
        return bool(
            (await db.execute(select(User.email_verified).where(User.email == email))).scalar_one()
        )


# --- the attack ------------------------------------------------------------------- #
async def test_google_refuses_to_adopt_an_unverified_password_account(client, account, as_google):
    """The finding itself.

    An attacker registered this address with a password and never proved the
    address. The real owner now signs in with Google. Before the fix this
    returned 200 and an owner session on the attacker's tenant.
    """
    made = await account(email_verified=False)
    as_google(made["email"])

    resp = await client.post("/api/auth/google", json={"id_token": "whatever"})

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "password_account_unverified"
    # No session of any kind came back.
    assert "access_token" not in resp.json()


async def test_the_refusal_does_not_verify_the_address_as_a_side_effect(client, account, as_google):
    """A refusal that still flipped the column would hand the attacker's
    account a confirmed address, and open the WhatsApp gate for them."""
    made = await account(email_verified=False)
    as_google(made["email"])

    await client.post("/api/auth/google", json={"id_token": "whatever"})

    assert await _verified(made["email"]) is False


# --- and the cases that must keep working ----------------------------------------- #
async def test_google_signs_into_a_verified_password_account(client, account, as_google):
    """Somebody who signed up with a password, confirmed the address, and later
    presses the Google button. Over-correcting here would break a real flow."""
    made = await account(email_verified=True)
    as_google(made["email"])

    resp = await client.post("/api/auth/google", json={"id_token": "whatever"})

    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == str(made["tenant_id"])


async def test_google_adopts_an_unverified_account_that_has_no_password(client, account, as_google):
    """Not the attack shape. With no password there is no second way into the
    row, so Google's assertion is the only credential it has ever had, and
    refusing would lock out every account created through Google before this
    column existed."""
    made = await account(email_verified=False, with_password=False)
    as_google(made["email"])

    resp = await client.post("/api/auth/google", json={"id_token": "whatever"})

    assert resp.status_code == 200
    # And the assertion is recorded, so the WhatsApp gate opens.
    assert await _verified(made["email"]) is True


async def test_resetting_the_password_confirms_the_address(client, account):
    """The route back from the 409 for somebody who forgot their password.

    A reset link is mailed to the address, so using it proves the same thing the
    confirmation link proves. Without this the 409 would be a dead end: bounced
    off Google, unable to remember the password, and the reset that follows
    would leave the address still unconfirmed.
    """
    made = await account(email_verified=False)
    async with _system_session() as db:
        user = (await db.execute(select(User).where(User.email == made["email"]))).scalar_one()
        reset_token = create_password_reset_token(user)

    resp = await client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "a-brand-new-password"},
    )

    assert resp.status_code == 204
    assert await _verified(made["email"]) is True


# --- what an unconfirmed account is held back from --------------------------------- #
async def test_an_unconfirmed_owner_cannot_connect_a_whatsapp_number(client, account):
    """The gate that makes a squatted account inert. Everything else about the
    trial stays open; this is the step that turns an address somebody typed into
    a live business identity on a real phone number."""
    made = await account(email_verified=False)
    login = await client.post(
        "/api/auth/login", json={"email": made["email"], "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["email_verified"] is False
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post("/api/sessions", json={"session_name": "main"}, headers=headers)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "email_unverified"


async def test_confirming_the_address_opens_the_gate(client, account):
    """The other half: the gate must actually lift, and it must lift from the
    database rather than from a claim in the token the user already holds."""
    made = await account(email_verified=False)
    login = await client.post(
        "/api/auth/login", json={"email": made["email"], "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    async with _system_session() as db:
        user = (await db.execute(select(User).where(User.email == made["email"]))).scalar_one()
        user.email_verified = True

    # Same token as before, deliberately: the check reads the database, so
    # confirming on one device must not leave another refusing until its token
    # expires.
    resp = await client.post("/api/sessions", json={"session_name": "main"}, headers=headers)

    assert resp.status_code != 403
