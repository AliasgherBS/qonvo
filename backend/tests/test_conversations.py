"""Owner inbox API: list, messages, reply (DESIGN.md §5.5, §10) — requires a
live, MIGRATED Postgres.

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5433/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    uv run pytest -m postgres tests/test_conversations.py

The reply endpoint's send gateway is mocked (per the task's test plan) — no
real WAHA/network call happens.
"""

from __future__ import annotations

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

from app.api.deps import get_arq, get_db, get_send_gateway, get_waha, require_tenant  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.conversation import Conversation, Message  # noqa: E402
from app.models.enums import (  # noqa: E402
    ConversationState,
    MessageAuthor,
    MessageDirection,
    MessageType,
)
from app.models.tenant import Tenant  # noqa: E402
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


@pytest.fixture
def mock_gateway():
    gateway = AsyncMock()
    gateway.send_text.return_value = {"id": "wa-outbound-1"}
    return gateway


@pytest.fixture
async def client(mock_gateway):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_arq] = lambda: AsyncMock()
    app.dependency_overrides[get_waha] = lambda: AsyncMock()
    app.dependency_overrides[get_send_gateway] = lambda: mock_gateway
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def _token_for(tenant_id: uuid.UUID) -> str:
    return create_access_token(
        subject="owner@example.com", tenant_id=tenant_id, role="owner", is_qonvo_admin=False
    )


@pytest.fixture
async def tenant_with_conversation():
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    session_name = f"conv-test-{tenant_id.hex[:8]}"
    chat_id = "923001112233@c.us"

    async with _system_session() as db:
        db.add(Tenant(id=tenant_id, name="Conv Test Co", slug=f"conv-test-{tenant_id.hex[:8]}"))
        db.add(WhatsAppSession(id=session_id, tenant_id=tenant_id, session_name=session_name))
        await db.flush()
        db.add(
            Conversation(
                id=conv_id,
                tenant_id=tenant_id,
                session_id=session_id,
                chat_id=chat_id,
                state=ConversationState.bot_active,
                unread_count=2,
            )
        )
        await db.flush()
        # Explicit, distinct created_at: both inserts land in one transaction, so
        # relying on the server_default now() would give them identical
        # timestamps and make ordering non-deterministic.
        now = datetime.now(UTC)
        db.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                wa_message_id="wa-in-1",
                direction=MessageDirection.inbound,
                author=MessageAuthor.customer,
                type=MessageType.text,
                body="hello there",
                created_at=now - timedelta(seconds=5),
            )
        )
        db.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                wa_message_id="wa-out-1",
                direction=MessageDirection.outbound,
                author=MessageAuthor.bot,
                type=MessageType.text,
                body="hi, how can I help?",
                created_at=now,
            )
        )

    try:
        yield {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "conversation_id": conv_id,
            "session_name": session_name,
            "chat_id": chat_id,
        }
    finally:
        async with _system_session() as db:
            await db.execute(delete(Message).where(Message.tenant_id == tenant_id))
            await db.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
            await db.execute(delete(WhatsAppSession).where(WhatsAppSession.tenant_id == tenant_id))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def test_list_conversations(client, tenant_with_conversation):
    headers = {"Authorization": f"Bearer {_token_for(tenant_with_conversation['tenant_id'])}"}
    resp = await client.get("/api/conversations", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(tenant_with_conversation["conversation_id"])
    assert item["chat_id"] == tenant_with_conversation["chat_id"]
    assert item["state"] == "bot_active"
    assert item["last_message_preview"] == "hi, how can I help?"
    assert item["unread"] == 2


async def test_list_conversations_filter_by_state(client, tenant_with_conversation):
    headers = {"Authorization": f"Bearer {_token_for(tenant_with_conversation['tenant_id'])}"}
    resp = await client.get("/api/conversations?state=needs_human", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


async def test_list_messages_and_clears_unread(client, tenant_with_conversation):
    headers = {"Authorization": f"Bearer {_token_for(tenant_with_conversation['tenant_id'])}"}
    conv_id = tenant_with_conversation["conversation_id"]

    resp = await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [m["body"] for m in items] == ["hello there", "hi, how can I help?"]
    assert items[0]["direction"] == "inbound"
    assert items[0]["author"] == "customer"
    assert items[1]["direction"] == "outbound"
    assert items[1]["author"] == "bot"

    async with _system_session() as db:
        row = (
            await db.execute(select(Conversation).where(Conversation.id == conv_id))
        ).scalar_one()
        assert row.unread_count == 0


async def test_reply_sends_via_gateway_and_logs_message(
    client, tenant_with_conversation, mock_gateway
):
    headers = {"Authorization": f"Bearer {_token_for(tenant_with_conversation['tenant_id'])}"}
    conv_id = tenant_with_conversation["conversation_id"]

    resp = await client.post(
        f"/api/conversations/{conv_id}/reply", json={"text": "on my way!"}, headers=headers
    )
    assert resp.status_code == 200
    message_id = resp.json()["message_id"]

    mock_gateway.send_text.assert_awaited_once()
    call_args = mock_gateway.send_text.await_args
    assert call_args.args[0] == tenant_with_conversation["session_name"]
    assert call_args.args[1] == tenant_with_conversation["chat_id"]
    assert call_args.args[2] == "on my way!"

    async with _system_session() as db:
        row = (
            await db.execute(select(Message).where(Message.id == uuid.UUID(message_id)))
        ).scalar_one()
        assert row.direction == MessageDirection.outbound
        assert row.author == MessageAuthor.human
        assert row.body == "on my way!"
        assert row.wa_message_id == "wa-outbound-1"


async def test_conversations_require_tenant_token(client):
    resp = await client.get("/api/conversations")
    assert resp.status_code == 401


async def test_conversation_not_found_in_other_tenant(client, tenant_with_conversation):
    other_tenant_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {_token_for(other_tenant_id)}"}
    conv_id = tenant_with_conversation["conversation_id"]
    resp = await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)
    assert resp.status_code == 404


async def test_rls_blocks_cross_tenant_conversation_read(tenant_with_conversation):
    """RLS itself — not just the app-layer ``tenant_id`` filter — hides another
    tenant's conversations, exercised on the new ``conversations``/``messages``
    columns added in this phase (DESIGN.md §3, §17)."""
    other_tenant_id = uuid.uuid4()
    async with _system_session() as db:
        db.add(Tenant(id=other_tenant_id, name="Other Co", slug=f"other-{other_tenant_id.hex[:8]}"))
    try:
        # Scoped to the *other* tenant, with zero app-layer WHERE clause: RLS
        # alone must still hide the first tenant's conversation row.
        async with _tenant_session(other_tenant_id) as db:
            rows = (await db.execute(select(Conversation))).scalars().all()
            assert rows == []

        # Scoped to the owning tenant: its own conversation is visible.
        async with _tenant_session(tenant_with_conversation["tenant_id"]) as db:
            rows = (await db.execute(select(Conversation))).scalars().all()
            assert [r.id for r in rows] == [tenant_with_conversation["conversation_id"]]
    finally:
        async with _system_session() as db:
            await db.execute(delete(Tenant).where(Tenant.id == other_tenant_id))
