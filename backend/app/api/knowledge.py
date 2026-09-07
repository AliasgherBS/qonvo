"""Knowledge base CRUD + gap review (DESIGN.md §6, §10).

The API's ``type:"url"`` maps onto the DB enum's ``website`` member (a URL
source *is* a website source — the enum predates this route and already
covers the concept under that name, so no migration/enum change is needed).
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from arq import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.storage import purge_source_files, source_dir
from app.api.deps import get_arq, get_db, require_tenant
from app.api.knowledge_limits import as_http_detail, check_room_for, usage_for
from app.core.limits import MAX_TEXT_ENTRY_CHARS, MAX_UPLOAD_BYTES, LimitExceeded, exceeded
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


def _cap_entry(v: str | None) -> str | None:
    """One pasted entry, about twenty pages. Rejected rather than truncated:
    a silently shortened price list answers customers with the half that fit."""
    if v is not None and len(v) > MAX_TEXT_ENTRY_CHARS:
        raise exceeded("A knowledge entry", limit=MAX_TEXT_ENTRY_CHARS, actual=len(v))
    return v


class CreateSourceRequest(BaseModel):
    type: SourceTypeIn
    title: str
    content: str | None = None
    url: str | None = None  # for type="url": the page to fetch + ingest

    _cap_content = field_validator("content")(classmethod(lambda cls, v: _cap_entry(v)))


class UpdateSourceRequest(BaseModel):
    title: str | None = None
    content: str | None = None

    _cap_content = field_validator("content")(classmethod(lambda cls, v: _cap_entry(v)))


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
    url = (body.url or "").strip() or None
    if db_type == KnowledgeSourceType.website and not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="a URL is required for a website source"
        )
    try:
        await check_room_for(
            db, tenant_id, new_source=True, added_chars=len(body.content or "")
        )
    except LimitExceeded as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=as_http_detail(err)
        ) from err
    row = KnowledgeSource(
        tenant_id=tenant_id,
        type=db_type,
        name=body.title,
        url=url,
        content=body.content,
        # Everything goes through the ingestion worker (chunk + embed, §6);
        # a source without chunks is invisible to RAG even if "stored".
        status="pending_ingest",
    )
    db.add(row)
    await db.flush()
    # Ingest now if there's inline content OR a URL to fetch (file uploads enqueue
    # from the upload route instead).
    if body.content or url:
        await arq.enqueue_job("ingest_knowledge_source", str(row.id), str(tenant_id))
    return _to_response(row)


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    """Full source incl. content — powers the dashboard view/edit dialog."""
    row = await _get_source(db, source_id, tenant_id)
    return _to_response(row)


@router.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    body: UpdateSourceRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
) -> SourceResponse:
    """Edit a source's title/content. A content change re-runs ingestion so the
    RAG index reflects the edit (a stale index would answer from old text)."""
    row = await _get_source(db, source_id, tenant_id)
    if body.content is not None:
        try:
            await check_room_for(
                db,
                tenant_id,
                added_chars=len(body.content),
                # What this edit removes. Without it, shrinking a source while
                # already at the cap would be refused for exceeding a total the
                # edit itself reduces.
                replacing_chars=len(row.content or ""),
            )
        except LimitExceeded as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=as_http_detail(err)
            ) from err
    if body.title is not None:
        row.name = body.title
    content_changed = body.content is not None and body.content != row.content
    if body.content is not None:
        row.content = body.content
    if content_changed:
        row.status = "pending_ingest"
    await db.flush()
    if content_changed and row.content:
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
    # The chunks go with the row; the uploaded file does not, and would
    # otherwise sit on the volume forever.
    purge_source_files(tenant_id, source_id)


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

    # Read in chunks and stop at the cap rather than `await file.read()`.
    # That call pulls the whole upload into the API process's memory before
    # anything can object, so a single large file was an availability problem
    # and not merely a cost one. Reading one chunk past the limit is enough to
    # know it is too big, and is the most memory that can ever be held.
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Files are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
                    "Split the document, or paste the part your rep needs."
                ),
            )
        chunks.append(chunk)
    data = b"".join(chunks)

    # A file can pass the per-file check and still push the tenant over its
    # total, so the plan limit is checked here too. Bytes are a stand-in for
    # characters at this point; the worker re-checks once it has real text.
    try:
        await check_room_for(db, tenant_id, added_bytes=total)
    except LimitExceeded as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=as_http_detail(err)
        ) from err

    safe_name = _SAFE_FILENAME.sub("_", file.filename or "upload.bin")
    dest_dir = source_dir(tenant_id, source_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    dest_path.write_bytes(data)

    row.status = "pending_ingest"
    row.meta = {
        **row.meta,
        "upload_path": str(dest_path),
        "content_type": file.content_type,
        # Recorded here so the disk quota can be summed in SQL. The raw file is
        # kept after ingestion so re-ingestion stays possible, which is exactly
        # why it needs a bound.
        "upload_bytes": total,
    }
    await db.flush()
    await arq.enqueue_job("ingest_knowledge_source", str(row.id), str(tenant_id))
    return _to_response(row)


@router.get("/usage")
async def knowledge_usage(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """What this tenant holds against what its plan allows.

    Exists so the knowledge page can show `used / cap` while someone types,
    rather than letting them write for ten minutes and refusing the save. The
    caps are enforced on write regardless; this only makes them visible.
    """
    return (await usage_for(db, tenant_id)).as_dict()


@router.get("/gaps")
async def knowledge_gaps(
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """What customers asked that the rep could not handle (§6, §7).

    Three different failures used to live in three different places, or nowhere,
    so an owner could only ever see part of the picture:

    * **retrieval miss** — nothing relevant was found. Adding knowledge fixes it.
    * **answer miss** — plenty was retrieved and the rep escalated anyway. More
      knowledge will NOT fix this: what exists does not actually answer the
      question. Recorded nowhere before.
    * **escalation** — the rep's own words about why it gave up, which were
      written to ``handoffs`` and shown to nobody.

    They answer one question, so they are one list, tagged by kind and ordered
    by how often each was asked.
    """
    question = AnalyticsEvent.data["question"].astext
    reason = AnalyticsEvent.data["reason"].astext
    had_context = AnalyticsEvent.data["had_context"].astext

    stmt = (
        select(
            question.label("question"),
            AnalyticsEvent.event_type.label("event_type"),
            func.max(had_context).label("had_context"),
            func.max(reason).label("reason"),
            func.count().label("count"),
            func.max(AnalyticsEvent.occurred_at).label("last_asked"),
        )
        .where(
            AnalyticsEvent.tenant_id == tenant_id,
            AnalyticsEvent.event_type.in_(("knowledge_gap", "escalation")),
            question.isnot(None),
        )
        .group_by(question, AnalyticsEvent.event_type)
        .order_by(func.count().desc(), func.max(AnalyticsEvent.occurred_at).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            # Question text identifies a gap; the kind separates two rows that
            # share it (asked once with no knowledge, once with the wrong kind).
            "id": f"{r.event_type}:{r.question}",
            "question": r.question,
            "kind": (
                "retrieval_miss"
                if r.event_type == "knowledge_gap"
                else ("answer_miss" if r.had_context == "true" else "escalation")
            ),
            "reason": r.reason,
            "count": r.count,
            "last_asked": r.last_asked,
        }
        for r in rows
    ]


__all__ = ["router"]
