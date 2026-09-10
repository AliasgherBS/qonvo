"""Knowledge base CRUD + gap review (DESIGN.md §6, §10).

The API's ``type:"url"`` maps onto the DB enum's ``website`` member (a URL
source *is* a website source — the enum predates this route and already
covers the concept under that name, so no migration/enum change is needed).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from arq import ArqRedis
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.ingestion import sanitise_extracted_text
from app.agent.storage import purge_source_files, source_dir
from app.api.deps import get_arq, get_claims, get_db, require_owner, require_tenant
from app.api.knowledge_limits import (
    SourceStats,
    as_http_detail,
    check_room_for,
    source_chars,
    source_stats,
    usage_for,
)
from app.core.limits import MAX_TEXT_ENTRY_CHARS, MAX_UPLOAD_BYTES, LimitExceeded, exceeded
from app.core.security import TokenClaims
from app.core.url_guard import UnsafeUrlError, validate_public_url
from app.models.enums import KnowledgeSourceType
from app.models.knowledge import KnowledgeSource
from app.models.ops import AnalyticsEvent
from app.services import audit
from app.services.usage import Meter

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

#: The two event types a gap row can be built from (see ``knowledge_gaps``).
_GAP_EVENT_TYPES = ("knowledge_gap", "escalation")

#: Written when an owner answers a gap by adding knowledge for it (teardown K1).
#: Gaps are *derived* from ``analytics_events`` rather than stored, so the
#: resolution is an event too: no new table, and a question asked again after
#: being answered comes back on its own, which is the honest behaviour --
#: the answer did not work and the owner needs to know that.
GAP_ANSWERED_EVENT = "knowledge_gap_answered"


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


#: H1 (VPS audit, 2026-09-11). A NUL byte reaching Postgres is a 500, and the
#: same byte reached it twice: first through file ingestion, where it hung a
#: real 391 KB PDF on "Processing" for ever, and then -- after that path was
#: sanitised -- straight through this JSON API instead. Fixing the parser was
#: fixing one door in a room with two.
#:
#: So it is applied at the request model, which is the boundary every entry
#: point crosses. ``sanitise_extracted_text`` is the function the file path
#: already uses, reused rather than reimplemented, so the two cannot drift.
def _clean_text(v: str | None) -> str | None:
    return None if v is None else sanitise_extracted_text(v)


class CreateSourceRequest(BaseModel):
    type: SourceTypeIn
    #: min_length=1 for M2: an empty title returned 201 and rendered a blank,
    #: unidentifiable row in the sources table. ``content`` had a length rule
    #: and ``title`` had only "required", which an empty string satisfies.
    title: str = Field(min_length=1, max_length=255)
    content: str | None = None
    url: str | None = None  # for type="url": the page to fetch + ingest
    # The gap this entry answers, if it was written from the Gaps table
    # (teardown K1). Carried on the create rather than closed by a second call
    # so the gap is marked answered exactly when the answer exists: there is no
    # intermediate state where a gap has been dismissed and nothing was taught.
    answers_gap_id: str | None = None

    _cap_content = field_validator("content")(classmethod(lambda cls, v: _cap_entry(v)))
    _clean = field_validator("title", "content")(classmethod(lambda cls, v: _clean_text(v)))


class UpdateSourceRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = None
    # Re-run ingestion for a source whose text lives somewhere else (K2). A
    # website's ``content`` column is NULL, so the content-changed path below
    # can never re-crawl one, and the only refresh control on the page reloaded
    # the table. Deliberately a flag on this route rather than a new
    # ``POST /sources/{id}/refetch``: re-fetching a source is the same
    # permission as editing one, and a second route is a second gate to keep in
    # step with the first.
    refetch: bool = False

    _cap_content = field_validator("content")(classmethod(lambda cls, v: _cap_entry(v)))
    _clean = field_validator("title", "content")(classmethod(lambda cls, v: _clean_text(v)))


class SourceResponse(BaseModel):
    id: UUID
    type: str
    title: str
    url: str | None
    content: str | None
    status: str
    #: Why an ingestion failed, in words the owner can act on (F5).
    #:
    #: The table read "Nothing indexed - Error" and the API carried no error
    #: field at all, so there was no way to tell a corrupt file from an
    #: unsupported variant from a bad minute, and no way to try again short of
    #: deleting and re-uploading.
    error: str | None = None
    auto_refresh: bool
    created_at: datetime
    # What a row could not say before (teardown K2): how much of it the rep
    # actually holds, how big the upload behind it was, and when a website was
    # last crawled. All three were already measured -- the size for the quota,
    # the bytes in ``meta`` -- and none of them reached the page.
    chars: int
    chunks: int
    upload_bytes: int | None
    last_ingested_at: datetime | None


def _to_response(row: KnowledgeSource, stats: SourceStats | None = None) -> SourceResponse:
    meta = row.meta or {}
    upload_bytes = meta.get("upload_bytes")
    return SourceResponse(
        id=row.id,
        type=_TYPE_DB_TO_OUT.get(row.type, row.type.value),
        title=row.name,
        url=row.url,
        content=row.content,
        status=row.status,
        error=meta.get("error") if row.status == "error" else None,
        auto_refresh=row.auto_refresh,
        created_at=row.created_at,
        chars=stats.chars if stats else 0,
        chunks=stats.chunks if stats else 0,
        # Only ever written as an int by the upload route; anything else in
        # there is somebody else's data and is reported as unknown, not as 0.
        upload_bytes=upload_bytes if isinstance(upload_bytes, int) else None,
        last_ingested_at=row.last_ingested_at,
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
    stats = await source_stats(db, tenant_id)
    return [_to_response(r, stats.get(r.id)) for r in rows]


def _checked_url(url: str | None) -> str | None:
    """Refuse a private or non-http URL here, not only in the worker.

    The worker validates again, and that is the check that matters because it
    is the one that sees each redirect hop. This one exists so the owner is
    told while the dialog is still open. Without it the only feedback is a
    source that quietly turns to "error" a few seconds later, which reads as
    the product failing rather than as the address being refused.
    """
    if not url:
        return url
    try:
        return validate_public_url(url)
    except UnsafeUrlError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


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
    url = _checked_url(url)
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
    if body.answers_gap_id:
        _mark_gap_answered(db, tenant_id, body.answers_gap_id, source_id=row.id)
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
    stats = await source_stats(db, tenant_id, source_id=row.id)
    return _to_response(row, stats.get(row.id))


@router.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    body: UpdateSourceRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
) -> SourceResponse:
    """Edit a source's title/content, or re-fetch it.

    A content change re-runs ingestion so the RAG index reflects the edit (a
    stale index would answer from old text). ``refetch`` re-runs it for a source
    whose text is not held here at all: a website, or an upload still on the
    volume.
    """
    row = await _get_source(db, source_id, tenant_id)
    refetch = False
    if body.refetch:
        # A manual entry has nothing to fetch: its text *is* the source, so
        # re-ingesting it would embed the same characters again. Refused loudly
        # rather than accepted as a no-op, because the button that sends this
        # is not offered for manual entries and a silent success would hide a
        # wiring mistake.
        refetch = bool(row.url or (row.meta or {}).get("upload_path"))
        if not refetch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="this source has nothing to re-fetch — edit its content instead",
            )
    if body.content is not None:
        try:
            await check_room_for(
                db,
                tenant_id,
                added_chars=len(body.content),
                # What this edit removes: the chunks this source currently
                # occupies, which re-ingestion will delete and rebuild. Not
                # len(row.content), which is NULL for anything uploaded or
                # fetched and would credit nothing.
                replacing_chars=await source_chars(db, row.id),
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
    if content_changed or refetch:
        row.status = "pending_ingest"
    await db.flush()
    if (content_changed and row.content) or refetch:
        await arq.enqueue_job("ingest_knowledge_source", str(row.id), str(tenant_id))
    stats = await source_stats(db, tenant_id, source_id=row.id)
    return _to_response(row, stats.get(row.id))


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    tenant_id: UUID = Depends(require_owner),  # grounding the rep silently loses
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_source(db, source_id, tenant_id)
    # Recorded before the delete: afterwards the name is gone, and "a source
    # was deleted" without saying which one is not a record of anything.
    await audit.record(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="knowledge_source_deleted",
        target=str(source_id),
        meta={"name": row.name, "type": row.type.value, "url": row.url},
    )
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
) -> dict:
    """What this tenant holds against what its plan allows.

    Exists so the knowledge page can show `used / cap` while someone types,
    rather than letting them write for ten minutes and refusing the save. The
    caps are enforced on write regardless; this only makes them visible.

    The raw counts stay where they were, and ``meters`` adds the same shape the
    billing page renders (teardown K3: these three caps were metered on the
    billing page and invisible on the page they govern). Meter-shaped rather
    than three ratios computed in the browser, because ``Meter.state`` is the
    one place that decides where amber starts -- see ``services/usage.py``.
    """
    usage = await usage_for(db, tenant_id)
    return {
        **usage.as_dict(),
        "meters": {
            "sources": Meter(used=usage.sources, allowed=usage.max_sources).as_dict(),
            "chars": Meter(used=usage.chars, allowed=usage.max_chars).as_dict(),
            # Megabytes, for the same reason the billing page uses them: nobody
            # reads "52,428,800 of 52,428,800" correctly.
            "upload_mb": Meter(
                used=usage.upload_bytes // (1024 * 1024),
                allowed=usage.max_upload_bytes // (1024 * 1024),
            ).as_dict(),
        },
    }


def _gap_question(gap_id: str) -> str:
    """The question inside a gap id.

    Ids are ``f"{event_type}:{question}"`` (see ``knowledge_gaps``), and the
    resolution is recorded against the question alone. Answering "do you
    deliver?" answers it whether the rep found nothing or found the wrong thing,
    and making the owner answer the same sentence twice is the dead end this
    was meant to remove.
    """
    prefix, _, rest = gap_id.partition(":")
    return rest if prefix in _GAP_EVENT_TYPES and rest else gap_id


def _mark_gap_answered(db: AsyncSession, tenant_id: UUID, gap_id: str, *, source_id: UUID) -> None:
    """Record that a gap now has an answer, so it stops being reported.

    Not flushed here; it rides the request's transaction with the source it
    answers. A marker without the source would hide a question nobody answered.
    """
    db.add(
        AnalyticsEvent(
            tenant_id=tenant_id,
            event_type=GAP_ANSWERED_EVENT,
            occurred_at=datetime.now(UTC),
            data={"question": _gap_question(gap_id), "source_id": str(source_id)},
        )
    )


def answered_gaps_subquery(tenant_id: UUID):
    """Questions this tenant has answered, and when it last answered them.

    Exported because ``/analytics/summary`` lists the same top gaps: a question
    that has been answered has to stop appearing on both pages, or the loop
    still looks like a dead end from one of them.
    """
    question = AnalyticsEvent.data["question"].astext
    return (
        select(
            question.label("question"),
            func.max(AnalyticsEvent.occurred_at).label("answered_at"),
        )
        .where(
            AnalyticsEvent.tenant_id == tenant_id,
            AnalyticsEvent.event_type == GAP_ANSWERED_EVENT,
        )
        .group_by(question)
        .subquery()
    )


def gaps_query(tenant_id: UUID, limit: int):
    """The gap aggregation, as a statement.

    Separated from the route so it can be compiled and read in a test without a
    database. The exclusion below is a HAVING over an outer join, which is the
    kind of thing that is either right or silently returns every row.
    """
    question = AnalyticsEvent.data["question"].astext
    reason = AnalyticsEvent.data["reason"].astext
    had_context = AnalyticsEvent.data["had_context"].astext
    answered = answered_gaps_subquery(tenant_id)

    return (
        select(
            question.label("question"),
            AnalyticsEvent.event_type.label("event_type"),
            func.max(had_context).label("had_context"),
            func.max(reason).label("reason"),
            func.count().label("count"),
            func.max(AnalyticsEvent.occurred_at).label("last_asked"),
        )
        .select_from(AnalyticsEvent)
        .outerjoin(answered, answered.c.question == question)
        .where(
            AnalyticsEvent.tenant_id == tenant_id,
            AnalyticsEvent.event_type.in_(_GAP_EVENT_TYPES),
            question.isnot(None),
        )
        .group_by(question, AnalyticsEvent.event_type, answered.c.answered_at)
        .having(
            or_(
                answered.c.answered_at.is_(None),
                func.max(AnalyticsEvent.occurred_at) > answered.c.answered_at,
            )
        )
        .order_by(func.count().desc(), func.max(AnalyticsEvent.occurred_at).desc())
        .limit(limit)
    )


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

    A gap the owner has already answered drops off (teardown K1). It comes back
    if the same question is asked *after* the answer was written, because then
    the answer demonstrably did not work -- which is worth more than a list that
    only ever grows.
    """
    rows = (await db.execute(gaps_query(tenant_id, limit))).all()

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


__all__ = ["GAP_ANSWERED_EVENT", "answered_gaps_subquery", "gaps_query", "router"]
