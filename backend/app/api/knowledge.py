"""Knowledge base CRUD + gap review (DESIGN.md §6, §10).

The API's ``type:"url"`` maps onto the DB enum's ``website`` member (a URL
source *is* a website source — the enum predates this route and already
covers the concept under that name, so no migration/enum change is needed).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from arq import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq, get_db, require_tenant
from app.core.config import settings
from app.models.enums import KnowledgeSourceType
from app.models.knowledge import KnowledgeSource
from app.models.ops import AnalyticsEvent

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class SourceTypeIn(StrEnum):
    manual = "manual"
    file = "file"
    url = "url"


_TYPE_IN_TO_DB = {
    SourceTypeIn.manual: KnowledgeSourceType.manual,
    SourceTypeIn.file: KnowledgeSourceType.file,
    SourceTypeIn.url: KnowledgeSourceType.website,
}
_TYPE_DB_TO_OUT = {v: k.value for k, v in _TYPE_IN_TO_DB.items()}


class CreateSourceRequest(BaseModel):
    type: SourceTypeIn
    title: str
    content: str | None = None


class SourceResponse(BaseModel):
    id: UUID
    type: str
    title: str
    url: str | None
    content: str | None
    status: str
    auto_refresh: bool
    created_at: datetime


def _to_response(row: KnowledgeSource) -> SourceResponse:
    return SourceResponse(
        id=row.id,
        type=_TYPE_DB_TO_OUT.get(row.type, row.type.value),
        title=row.name,
        url=row.url,
        content=row.content,
        status=row.status,
        auto_refresh=row.auto_refresh,
        created_at=row.created_at,
    )


async def _get_source(db: AsyncSession, source_id: UUID, tenant_id: UUID) -> KnowledgeSource:
    row = (
        await db.execute(
            select(KnowledgeSource).where(
                KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="knowledge source not found"
        )
    return row


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[SourceResponse]:
    rows = (
        await db.execute(
            select(KnowledgeSource)
            .where(KnowledgeSource.tenant_id == tenant_id)
            .order_by(KnowledgeSource.created_at.desc())
        )
    ).scalars().all()
    return [_to_response(r) for r in rows]


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: CreateSourceRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
) -> SourceResponse:
    db_type = _TYPE_IN_TO_DB[body.type]
    row = KnowledgeSource(
        tenant_id=tenant_id,
        type=db_type,
        name=body.title,
        content=body.content,
        # Everything goes through the ingestion worker (chunk + embed, §6);
        # a source without chunks is invisible to RAG even if "stored".
        status="pending_ingest",
    )
    db.add(row)
    await db.flush()
    if body.content:
        await arq.enqueue_job("ingest_knowledge_source", str(row.id), str(tenant_id))
    return _to_response(row)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_source(db, source_id, tenant_id)
    await db.delete(row)


@router.post("/sources/{source_id}/upload", response_model=SourceResponse)
async def upload_source_file(
    source_id: UUID,
    file: UploadFile = File(...),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
) -> SourceResponse:
    """Store the raw upload for later ingestion.

    Falls back to a local volume path — there is no MinIO client wired up yet
    in this codebase (DESIGN.md §12.3 calls for one; adding the SDK/client is
    out of scope here, so this stores to ``settings.knowledge_upload_dir``).
    """
    row = await _get_source(db, source_id, tenant_id)
    data = await file.read()

    safe_name = _SAFE_FILENAME.sub("_", file.filename or "upload.bin")
    dest_dir = Path(settings.knowledge_upload_dir) / str(tenant_id) / str(source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    dest_path.write_bytes(data)

    row.status = "pending_ingest"
    row.meta = {**row.meta, "upload_path": str(dest_path), "content_type": file.content_type}
    await db.flush()
    await arq.enqueue_job("ingest_knowledge_source", str(row.id), str(tenant_id))
    return _to_response(row)


@router.get("/gaps")
async def knowledge_gaps(
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Recent ``knowledge_gap`` analytics events — unanswered/handed-off questions (§6)."""
    rows = (
        await db.execute(
            select(AnalyticsEvent)
            .where(
                AnalyticsEvent.tenant_id == tenant_id,
                AnalyticsEvent.event_type == "knowledge_gap",
            )
            .order_by(AnalyticsEvent.occurred_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "conversation_id": str(r.conversation_id) if r.conversation_id else None,
            "occurred_at": r.occurred_at,
            "data": r.data,
        }
        for r in rows
    ]


__all__ = ["router"]
