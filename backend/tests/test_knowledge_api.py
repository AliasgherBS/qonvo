"""Knowledge source CRUD + upload + gaps (DESIGN.md §6, §10) — requires a live,
MIGRATED Postgres.

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5433/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    uv run pytest -m postgres tests/test_knowledge_api.py
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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

from app.api.deps import get_arq, get_db, get_waha, require_tenant  # noqa: E402
from app.core import config as config_module  # noqa: E402
from app.core.tenancy import set_tenant  # noqa: E402
from app.main import app  # noqa: E402
from app.models.knowledge import KnowledgeSource  # noqa: E402
from app.models.ops import AnalyticsEvent  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
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


@pytest.fixture
async def client(tmp_upload_dir):
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_arq] = lambda: AsyncMock()
    app.dependency_overrides[get_waha] = lambda: AsyncMock()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def tmp_upload_dir(monkeypatch):
    """Redirect the local-volume upload fallback to a throwaway directory."""
    tmp_dir = tempfile.mkdtemp(prefix="qonvo-knowledge-test-")
    monkeypatch.setattr(config_module.settings, "knowledge_upload_dir", tmp_dir)
    try:
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _token_for(tenant_id: uuid.UUID) -> str:
    return create_access_token(
        subject="owner@example.com", tenant_id=tenant_id, role="owner", is_qonvo_admin=False
    )


@pytest.fixture
async def tenant_id():
    tid = uuid.uuid4()
    async with _system_session() as db:
        db.add(Tenant(id=tid, name="Knowledge Test Co", slug=f"kb-test-{tid.hex[:8]}"))
    try:
        yield tid
    finally:
        async with _system_session() as db:
            await db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.tenant_id == tid))
            await db.execute(delete(KnowledgeSource).where(KnowledgeSource.tenant_id == tid))
            await db.execute(delete(Tenant).where(Tenant.id == tid))


async def test_create_manual_source(client, tenant_id):
    headers = {"Authorization": f"Bearer {_token_for(tenant_id)}"}
    resp = await client.post(
        "/api/knowledge/sources",
        json={"type": "manual", "title": "Return policy", "content": "Returns within 14 days."},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "manual"
    assert body["title"] == "Return policy"
    assert body["content"] == "Returns within 14 days."
    assert body["status"] == "ready"


async def test_create_url_source_maps_to_website_and_pending(client, tenant_id):
    headers = {"Authorization": f"Bearer {_token_for(tenant_id)}"}
    resp = await client.post(
        "/api/knowledge/sources",
        json={"type": "url", "title": "FAQ page"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "url"
    assert body["status"] == "pending_ingest"


async def test_list_and_delete_source(client, tenant_id):
    headers = {"Authorization": f"Bearer {_token_for(tenant_id)}"}
    create = await client.post(
        "/api/knowledge/sources",
        json={"type": "manual", "title": "Hours", "content": "9-5 Mon-Fri"},
        headers=headers,
    )
    source_id = create.json()["id"]

    listed = await client.get("/api/knowledge/sources", headers=headers)
    assert listed.status_code == 200
    assert any(s["id"] == source_id for s in listed.json())

    deleted = await client.delete(f"/api/knowledge/sources/{source_id}", headers=headers)
    assert deleted.status_code == 204

    listed_again = await client.get("/api/knowledge/sources", headers=headers)
    assert all(s["id"] != source_id for s in listed_again.json())


async def test_upload_file_marks_pending_ingest(client, tenant_id, tmp_upload_dir):
    headers = {"Authorization": f"Bearer {_token_for(tenant_id)}"}
    create = await client.post(
        "/api/knowledge/sources",
        json={"type": "file", "title": "Brochure"},
        headers=headers,
    )
    source_id = create.json()["id"]
    assert create.json()["status"] == "pending_ingest"

    upload = await client.post(
        f"/api/knowledge/sources/{source_id}/upload",
        files={"file": ("brochure.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        headers=headers,
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["status"] == "pending_ingest"

    # File actually landed on the (redirected) local volume path.
    found = list(__import__("pathlib").Path(tmp_upload_dir).rglob("brochure.pdf"))
    assert len(found) == 1
    assert found[0].read_bytes() == b"%PDF-1.4 fake content"


async def test_knowledge_gaps_lists_recent_events(client, tenant_id):
    headers = {"Authorization": f"Bearer {_token_for(tenant_id)}"}
    async with _tenant_session(tenant_id) as db:
        db.add(
            AnalyticsEvent(
                tenant_id=tenant_id,
                event_type="knowledge_gap",
                occurred_at=datetime.now(UTC),
                data={"question": "do you ship internationally?"},
            )
        )
        db.add(
            AnalyticsEvent(
                tenant_id=tenant_id,
                event_type="message_received",
                occurred_at=datetime.now(UTC),
                data={},
            )
        )

    resp = await client.get("/api/knowledge/gaps", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["data"]["question"] == "do you ship internationally?"


async def test_knowledge_routes_require_tenant_token(client):
    resp = await client.get("/api/knowledge/sources")
    assert resp.status_code == 401
