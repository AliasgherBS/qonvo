"""Owner inbox: list/read conversations, take-over/release, reply-as-business
(DESIGN.md §5.5, §10).

Every read path calls :func:`app.services.takeover.maybe_auto_resume` first —
there is no dedicated cron for the auto-resume TTL in Phase 1 (see that
module's docstring), so a stale pause self-heals here instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_send_gateway, require_tenant
from app.models.conversation import Conversation, Message
from app.models.enums import ConversationState, MessageAuthor, MessageDirection, MessageType
from app.models.whatsapp import WhatsAppSession
from app.services import takeover as takeover_service
from app.waha.send_gateway import DailyCapExceeded, SendGateway, SessionPacing

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationItem(BaseModel):
    id: UUID
    chat_id: str
    state: str
    last_message_preview: str | None
    last_activity_at: datetime
    unread: int


class ConversationListResponse(BaseModel):
    items: list[ConversationItem]
    total: int


class MessageItem(BaseModel):
    id: UUID
    direction: str
    author: str
    type: str
    body: str | None
    created_at: datetime


class MessageListResponse(BaseModel):
    items: list[MessageItem]


class StateResponse(BaseModel):
    state: str


class ReplyRequest(BaseModel):
    text: str


class ReplyResponse(BaseModel):
    message_id: UUID


async def _get_conversation(
    db: AsyncSession, conversation_id: UUID, tenant_id: UUID
) -> Conversation:
    row = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return row


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    state: ConversationState | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    filters = [Conversation.tenant_id == tenant_id, Conversation.active.is_(True)]
    if state is not None:
        filters.append(Conversation.state == state)

    total = (
        await db.execute(select(func.count()).select_from(Conversation).where(*filters))
    ).scalar_one()

    preview_subq = (
        select(Message.body)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Conversation, preview_subq)
            .where(*filters)
            .order_by(Conversation.last_activity_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    items = []
    for conversation, preview in rows:
        takeover_service.maybe_auto_resume(conversation)
        items.append(
            ConversationItem(
                id=conversation.id,
                chat_id=conversation.chat_id,
                state=conversation.state.value,
                last_message_preview=preview,
                last_activity_at=conversation.last_activity_at,
                unread=conversation.unread_count,
            )
        )
    return ConversationListResponse(items=items, total=total)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = None,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> MessageListResponse:
    conversation = await _get_conversation(db, conversation_id, tenant_id)
    takeover_service.maybe_auto_resume(conversation)

    filters = [Message.tenant_id == tenant_id, Message.conversation_id == conversation.id]
    if before is not None:
        filters.append(Message.created_at < before)
    rows = (
        await db.execute(
            select(Message).where(*filters).order_by(Message.created_at.desc()).limit(limit)
        )
    ).scalars().all()

    # Viewing the thread clears the inbox unread badge.
    conversation.unread_count = 0

    items = [
        MessageItem(
            id=m.id,
            direction=m.direction.value,
            author=m.author.value,
            type=m.type.value,
            body=m.body,
            created_at=m.created_at,
        )
        for m in reversed(rows)
    ]
    return MessageListResponse(items=items)


@router.post("/{conversation_id}/takeover", response_model=StateResponse)
async def take_over(
    conversation_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> StateResponse:
    conversation = await _get_conversation(db, conversation_id, tenant_id)
    takeover_service.takeover(conversation)
    return StateResponse(state=conversation.state.value)


@router.post("/{conversation_id}/release", response_model=StateResponse)
async def release_conversation(
    conversation_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> StateResponse:
    conversation = await _get_conversation(db, conversation_id, tenant_id)
    takeover_service.release(conversation)
    return StateResponse(state=conversation.state.value)


@router.post("/{conversation_id}/reply", response_model=ReplyResponse)
async def reply(
    conversation_id: UUID,
    body: ReplyRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    gateway: SendGateway = Depends(get_send_gateway),
) -> ReplyResponse:
    """Send an owner/staff reply through the send gateway, logged as ``author=human``
    (DESIGN.md §5.5, §5.6). Never calls the WAHA client directly."""
    conversation = await _get_conversation(db, conversation_id, tenant_id)
    session_row = (
        await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.id == conversation.session_id)
        )
    ).scalar_one_or_none()
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="conversation has no associated WhatsApp session",
        )

    pacing = SessionPacing(daily_cap=session_row.daily_cap, warmup_stage=session_row.warmup_stage)
    try:
        result = await gateway.send_text(
            session_row.session_name, conversation.chat_id, body.text, pacing=pacing
        )
    except DailyCapExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    now = datetime.now(UTC)
    wa_message_id = result.get("id") if isinstance(result, dict) else None
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        wa_message_id=wa_message_id,
        direction=MessageDirection.outbound,
        author=MessageAuthor.human,
        type=MessageType.text,
        body=body.text,
        wa_timestamp=now,
    )
    db.add(message)
    await db.flush()

    conversation.last_activity_at = now
    conversation.human_last_message_at = now

    return ReplyResponse(message_id=message.id)


__all__ = ["router"]
