"""A provider outage must not lose the customer's message.

Regression test for the fault found on 2026-09-04. The whole turn used to run
in one transaction, so when the LLM call exhausted its retries the rollback took
the inbound message, the conversation, the handoff and the notification with it
-- while the "a customer needs a human" email had already been sent. The owner
got an alert and found an empty inbox, and because dedupe is Redis-keyed for 24h
a WhatsApp redelivery was then dropped as a duplicate: the message was gone.

Requires a live, MIGRATED Postgres (same env as test_admin):
    QONVO_TEST_DATABASE_URL=... QONVO_TEST_SYSTEM_DATABASE_URL=... \\
    uv run pytest -m postgres tests/test_pipeline_persistence.py
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

pytestmark = pytest.mark.postgres

_APP_URL = os.environ.get("QONVO_TEST_DATABASE_URL")
_SYSTEM_URL = os.environ.get("QONVO_TEST_SYSTEM_DATABASE_URL")

if _APP_URL is None or _SYSTEM_URL is None:
    pytest.skip(
        "QONVO_TEST_DATABASE_URL / QONVO_TEST_SYSTEM_DATABASE_URL not set",
        allow_module_level=True,
    )

from app.core.tenancy import set_tenant  # noqa: E402
from app.models.conversation import Conversation, Message  # noqa: E402
from app.models.enums import SessionStatus  # noqa: E402
from app.models.tenant import Tenant, TenantConfig  # noqa: E402
from app.models.whatsapp import WhatsAppSession  # noqa: E402
from app.providers.openai_compat import ProviderError  # noqa: E402
from app.workers import pipeline as pl  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

_engine = create_async_engine(_APP_URL, poolclass=NullPool)
_system_engine = create_async_engine(_SYSTEM_URL, poolclass=NullPool)
_Session = async_sessionmaker(_engine, expire_on_commit=False)
_SystemSession = async_sessionmaker(_system_engine, expire_on_commit=False)


@asynccontextmanager
async def _tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    async with _Session() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session


class _DeadGateway:
    """Sends go nowhere; this test is about what survives in the database."""

    async def send_text(self, *_a, **_k):
        return {}

    async def send_voice(self, *_a, **_k):
        return {}


@pytest.fixture
async def tenant(monkeypatch):
    """A tenant with a session row, wired so the pipeline uses the test engine."""
    tenant_id = uuid.uuid4()
    async with _SystemSession() as db, db.begin():
        db.add(
            Tenant(
                id=tenant_id,
                name="Outage Co",
                slug=f"outage-{tenant_id.hex[:8]}",
                plan="trial",
                trial_ends_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=5),
            )
        )
        await db.flush()
        db.add(TenantConfig(tenant_id=tenant_id))
        db.add(
            WhatsAppSession(
                tenant_id=tenant_id,
                session_name=f"outage-{tenant_id.hex[:8]}",
                status=SessionStatus.working,
                engine="NOWEB",
                hmac_secret="x",
            )
        )

    monkeypatch.setattr(pl, "tenant_session", _tenant_session)
    yield tenant_id

    async with _SystemSession() as db, db.begin():
        await db.execute(delete(Message).where(Message.tenant_id == tenant_id))
        await db.execute(delete(Conversation).where(Conversation.tenant_id == tenant_id))
        await db.execute(delete(WhatsAppSession).where(WhatsAppSession.tenant_id == tenant_id))
        await db.execute(delete(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
        await db.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def _session_name(tenant_id: uuid.UUID) -> str:
    async with _tenant_session(tenant_id) as db:
        return (
            await db.execute(
                select(WhatsAppSession.session_name).where(
                    WhatsAppSession.tenant_id == tenant_id
                )
            )
        ).scalar_one()


async def _stored_messages(tenant_id: uuid.UUID) -> list[Message]:
    async with _tenant_session(tenant_id) as db:
        return list(
            (
                await db.execute(select(Message).where(Message.tenant_id == tenant_id))
            ).scalars()
        )


def _break_the_llm(monkeypatch):
    """Every LLM call fails, the way an exhausted quota or an outage does."""

    def _raise(*_a, **_k):
        raise ProviderError("/chat/completions failed (429): quota exhausted")

    monkeypatch.setattr(pl, "resolve_llm", _raise)
    monkeypatch.setattr(pl, "resolve_embedding", _raise)


async def test_inbound_message_survives_an_llm_outage(tenant, monkeypatch):
    """The customer wrote in. That fact must outlive the provider."""
    _break_the_llm(monkeypatch)
    session_name = await _session_name(tenant)

    with pytest.raises(ProviderError):
        await pl.run_pipeline(
            [pl.InboundFragment(message_id="outage-1", body="are you open today?")],
            session=session_name,
            chat_id="923001112222@c.us",
            tenant_id=str(tenant),
            send_gateway=_DeadGateway(),
        )

    stored = await _stored_messages(tenant)
    assert [m.wa_message_id for m in stored] == ["outage-1"]
    assert stored[0].body == "are you open today?"


async def test_the_conversation_survives_an_llm_outage(tenant, monkeypatch):
    """Without the conversation row the message is not reachable from the inbox."""
    _break_the_llm(monkeypatch)
    session_name = await _session_name(tenant)

    with pytest.raises(ProviderError):
        await pl.run_pipeline(
            [pl.InboundFragment(message_id="outage-2", body="hello?")],
            session=session_name,
            chat_id="923001112223@c.us",
            tenant_id=str(tenant),
            send_gateway=_DeadGateway(),
        )

    async with _tenant_session(tenant) as db:
        chats = list(
            (
                await db.execute(
                    select(Conversation.chat_id).where(Conversation.tenant_id == tenant)
                )
            ).scalars()
        )
    assert chats == ["923001112223@c.us"]


async def test_a_retry_does_not_duplicate_the_message(tenant, monkeypatch):
    """arq retries the whole job, so the persistence step runs again.

    It has to be idempotent, or the retry dies on the wa_message_id unique
    constraint and the reply is never attempted at all -- turning a transient
    provider blip into a permanently unanswered customer.
    """
    _break_the_llm(monkeypatch)
    session_name = await _session_name(tenant)

    for _ in range(3):
        with pytest.raises(ProviderError):
            await pl.run_pipeline(
                [pl.InboundFragment(message_id="outage-3", body="still there?")],
                session=session_name,
                chat_id="923001112224@c.us",
                tenant_id=str(tenant),
                send_gateway=_DeadGateway(),
            )

    stored = await _stored_messages(tenant)
    assert len(stored) == 1, "the same inbound message was stored more than once"
