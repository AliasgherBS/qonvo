"""Human takeover state machine: explicit API, implicit fromMe, and auto-resume
TTL (DESIGN.md §5.5) — requires a live, MIGRATED Postgres.

Same convention as ``test_rls_postgres.py``:

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5433/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    uv run pytest -m postgres tests/test_takeover.py

The ``message.any``/``fromMe`` webhook branch resolves its session and writes
its implicit-takeover conversation row through ``app.core.tenancy.system_session``
directly (not a FastAPI dependency — see ``app.api.webhooks``), so those tests
monkeypatch ``app.api.webhooks.system_session`` to point at the test engine
instead of overriding a dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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

import app.api.webhooks as webhooks_module  # noqa: E402
from app.api.deps import get_arq, get_db, require_tenant  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.enums import ConversationState  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.whatsapp import WhatsAppSession  # noqa: E402
from app.services.takeover import (  # noqa: E402
    is_auto_resume_due,
    maybe_auto_resume,
    release,
    takeover,
)
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

_HMAC_SECRET = "test-webhook-hmac-secret"


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


@pytest.fixture
async def client(monkeypatch):
    # webhooks.py calls system_session() directly (not a Depends chain), so the
    # webhook route needs a real monkeypatch rather than a dependency override.
    monkeypatch.setattr(webhooks_module, "system_session", _system_session)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_arq] = lambda: AsyncMock()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def whatsapp_session():
    """A tenant with one WAHA session, ready for a conversation to attach to."""
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session_name = f"takeover-test-{tenant_id.hex[:8]}"
    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="Takeover Test Co", slug=f"takeover-{tenant_id.hex[:8]}"))
        db.add(
            WhatsAppSession(
                id=session_id,
                tenant_id=tenant_id,
                session_name=session_name,
                hmac_secret=_HMAC_SECRET,
            )
        )
    try:
        yield {"tenant_id": tenant_id, "session_id": session_id, "session_name": session_name}
    finally:
        async with _system_session() as db:
            await db.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
            await db.execute(delete(WhatsAppSession).where(WhatsAppSession.tenant_id == tenant_id))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


def _sign(body: bytes) -> str:
    return hmac.new(_HMAC_SECRET.encode(), body, hashlib.sha512).hexdigest()


async def _get_conversation(
    tenant_id: uuid.UUID, session_id: uuid.UUID, chat_id: str
) -> Conversation | None:
    async with _system_session() as db:
        result = await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.session_id == session_id,
                Conversation.chat_id == chat_id,
            )
        )
        return result.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Implicit takeover via webhook message.any + fromMe
# --------------------------------------------------------------------------- #
async def test_from_me_triggers_implicit_takeover(client, whatsapp_session):
    chat_id = "923001234567@c.us"
    payload = {
        "event": "message.any",
        "session": whatsapp_session["session_name"],
        "payload": {
            "id": "wa-from-me-1",
            "from": chat_id,
            "fromMe": True,
            "body": "handled it myself",
        },
    }
    raw = json.dumps(payload).encode()
    resp = await client.post(
        "/webhooks/waha", content=raw, headers={"X-Webhook-Hmac": _sign(raw)}
    )
    assert resp.status_code == 200

    conversation = await _get_conversation(
        whatsapp_session["tenant_id"], whatsapp_session["session_id"], chat_id
    )
    assert conversation is not None
    assert conversation.state == ConversationState.paused_by_owner
    assert conversation.paused_until is not None
    assert conversation.human_last_message_at is not None


async def test_from_me_on_group_chat_ignored(client, whatsapp_session):
    chat_id = "120363000000000000@g.us"
    payload = {
        "event": "message.any",
        "session": whatsapp_session["session_name"],
        "payload": {"id": "wa-from-me-2", "from": chat_id, "fromMe": True, "body": "group reply"},
    }
    raw = json.dumps(payload).encode()
    resp = await client.post(
        "/webhooks/waha", content=raw, headers={"X-Webhook-Hmac": _sign(raw)}
    )
    assert resp.status_code == 200

    conversation = await _get_conversation(
        whatsapp_session["tenant_id"], whatsapp_session["session_id"], chat_id
    )
    assert conversation is None


# --------------------------------------------------------------------------- #
# Explicit takeover / release via the conversations API
# --------------------------------------------------------------------------- #
@pytest.fixture
async def conversation(whatsapp_session):
    conv_id = uuid.uuid4()
    async with _system_session() as db:
        db.add(
            Conversation(
                id=conv_id,
                tenant_id=whatsapp_session["tenant_id"],
                session_id=whatsapp_session["session_id"],
                chat_id="14155550123@c.us",
                state=ConversationState.bot_active,
            )
        )
    yield {**whatsapp_session, "conversation_id": conv_id}


def _token_for(tenant_id: uuid.UUID) -> str:
    from app.services.auth import create_access_token

    return create_access_token(
        subject="owner@example.com", tenant_id=tenant_id, role="owner", is_qonvo_admin=False
    )


async def test_explicit_takeover_and_release(client, conversation):
    headers = {"Authorization": f"Bearer {_token_for(conversation['tenant_id'])}"}
    conv_id = conversation["conversation_id"]

    resp = await client.post(f"/api/conversations/{conv_id}/takeover", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "paused_by_owner"

    resp = await client.post(f"/api/conversations/{conv_id}/release", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "bot_active"


# --------------------------------------------------------------------------- #
# Auto-resume TTL (pure state-machine unit tests — no HTTP needed)
# --------------------------------------------------------------------------- #
def test_takeover_sets_paused_until():
    conv = Conversation(state=ConversationState.bot_active)
    takeover(conv)
    assert conv.state == ConversationState.paused_by_owner
    assert conv.paused_until is not None
    assert conv.paused_until > datetime.now(UTC)


def test_release_clears_paused_until():
    conv = Conversation(state=ConversationState.paused_by_owner, paused_until=datetime.now(UTC))
    release(conv)
    assert conv.state == ConversationState.bot_active
    assert conv.paused_until is None


def test_auto_resume_due_after_ttl():
    conv = Conversation(
        state=ConversationState.paused_by_owner,
        paused_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert is_auto_resume_due(conv) is True


def test_auto_resume_not_due_before_ttl():
    conv = Conversation(
        state=ConversationState.paused_by_owner,
        paused_until=datetime.now(UTC) + timedelta(hours=1),
    )
    assert is_auto_resume_due(conv) is False


def test_maybe_auto_resume_transitions_when_due():
    conv = Conversation(
        state=ConversationState.paused_by_owner,
        paused_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    resumed = maybe_auto_resume(conv)
    assert resumed is True
    assert conv.state == ConversationState.bot_active
    assert conv.paused_until is None


def test_maybe_auto_resume_noop_when_bot_active():
    conv = Conversation(state=ConversationState.bot_active, paused_until=None)
    assert maybe_auto_resume(conv) is False


async def test_conversations_list_auto_resumes_expired_pause(client, conversation):
    conv_id = conversation["conversation_id"]
    async with _system_session() as db:
        row = (
            await db.execute(select(Conversation).where(Conversation.id == conv_id))
        ).scalar_one()
        row.state = ConversationState.paused_by_owner
        row.paused_until = datetime.now(UTC) - timedelta(seconds=1)

    headers = {"Authorization": f"Bearer {_token_for(conversation['tenant_id'])}"}
    resp = await client.get("/api/conversations", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(item["id"] == str(conv_id) and item["state"] == "bot_active" for item in items)
