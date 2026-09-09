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
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_db, get_send_gateway, require_tenant
from app.core.security import TokenClaims
from app.models.conversation import Conversation, Message
from app.models.enums import ConversationState, MessageAuthor, MessageDirection, MessageType
from app.models.whatsapp import WhatsAppSession
from app.services import audit
from app.services import takeover as takeover_service
from app.waha.send_gateway import DailyCapExceeded, SendGateway, SessionPacing

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

# 1:1 chat id suffixes. ``@c.us`` (and NOWEB's ``@s.whatsapp.net``) carry a real
# phone number; ``@lid`` is WhatsApp's privacy-preserving Linked ID and is NOT a
# number, so formatting it as one would invent a phone that does not exist.
_PHONE_SUFFIXES = ("@c.us", "@s.whatsapp.net")
_LID_SUFFIX = "@lid"

# Country calling code lengths, so "+92 300 999 8877" splits at the right place
# without pulling in libphonenumber for one label. Codes beginning 1 or 7 are a
# single digit, the ranges below are two, everything else is three (ITU E.164).
_TWO_DIGIT_CC = {
    "20", "27", "30", "31", "32", "33", "34", "36", "39", "40", "41", "43", "44",
    "45", "46", "47", "48", "49", "51", "52", "53", "54", "55", "56", "57", "58",
    "60", "61", "62", "63", "64", "65", "66", "81", "82", "84", "86", "90", "91",
    "92", "93", "94", "95", "98",
}


def _country_code_length(digits: str) -> int:
    if digits[:1] in ("1", "7"):
        return 1
    if digits[:2] in _TWO_DIGIT_CC:
        return 2
    return 3


def _group_national(digits: str) -> list[str]:
    """Split a national number into readable groups (3-3-4 for ten digits).

    The last four digits are kept together and the rest is cut into threes, so
    a group is never a single orphan digit ("+92 300 999 8 877" reads as a
    typo). A one- or two-digit remainder at the end of the head is merged back,
    which is also what the local convention happens to be where it matters
    (Malta's 9900 1234, China's 138 0013 8000).
    """
    if len(digits) <= 4:
        return [digits]
    head, tail = digits[:-4], digits[-4:]
    groups = [head[i : i + 3] for i in range(0, len(head), 3)]
    if len(groups) > 1 and len(groups[-1]) < 3:
        groups[-2:] = ["".join(groups[-2:])]
    return [*groups, tail]


def format_phone_number(chat_id: str) -> str:
    """``923009998877@c.us`` -> ``+92 300 999 8877``."""
    digits = "".join(ch for ch in chat_id.split("@", 1)[0] if ch.isdigit())
    if not digits:
        return chat_id
    if len(digits) <= 5:
        # Too short to be a real international number (a test double, usually).
        return f"+{digits}"
    cc_len = _country_code_length(digits)
    cc, national = digits[:cc_len], digits[cc_len:]
    return " ".join([f"+{cc}", *_group_national(national)])


def customer_display_name(chat_id: str, customer_name: str | None = None) -> str:
    """What the owner should see instead of a WhatsApp internal address (teardown I1).

    The push name when WhatsApp gave us one, a formatted phone number when the
    chat id contains one, and a short stable label for a Linked ID, which is not
    a phone number and must not be dressed up as one. The raw address is still
    returned by the API so the UI can keep it in a tooltip.
    """
    name = (customer_name or "").strip()
    if name:
        return name
    if chat_id.endswith(_PHONE_SUFFIXES):
        return format_phone_number(chat_id)
    if chat_id.endswith(_LID_SUFFIX):
        # Last four digits are enough to tell two unnamed customers apart in a
        # list, which is the whole job of this label.
        digits = "".join(ch for ch in chat_id.split("@", 1)[0] if ch.isdigit())
        return f"WhatsApp user {digits[-4:]}" if digits else "WhatsApp user"
    return chat_id


class ConversationItem(BaseModel):
    id: UUID
    chat_id: str
    # The WhatsApp push name, when a payload has carried one. NULL until then.
    customer_name: str | None
    # Server-rendered label so the inbox, the notification bell and anything
    # added later cannot drift apart on how a customer is named.
    display_name: str
    state: str
    last_message_preview: str | None
    last_activity_at: datetime
    unread: int


class ConversationListResponse(BaseModel):
    items: list[ConversationItem]
    total: int
    # Conversations with at least one unread inbound message, over the whole
    # active set rather than the current page or tab: it drives the count on the
    # All tab, which must not change when you page or filter (teardown I4).
    unread_conversations: int


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
    q: str | None = Query(default=None, max_length=64, description="Search name or number"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    filters = [Conversation.tenant_id == tenant_id, Conversation.active.is_(True)]
    if state is not None:
        filters.append(Conversation.state == state)
    if q and q.strip():
        # Search happens here rather than in the browser because the inbox is
        # paged: filtering the loaded page would hide the match the owner is
        # looking for as soon as a tenant has more conversations than one page
        # (teardown I4). Digits are matched against the raw chat id, so a typed
        # "+92 300" still finds 923009998877@c.us.
        needle = q.strip()
        digits = "".join(ch for ch in needle if ch.isdigit())
        clauses = [Conversation.customer_name.ilike(f"%{needle}%")]
        if digits:
            clauses.append(Conversation.chat_id.like(f"%{digits}%"))
        else:
            clauses.append(Conversation.chat_id.ilike(f"%{needle}%"))
        filters.append(or_(*clauses))

    total = (
        await db.execute(select(func.count()).select_from(Conversation).where(*filters))
    ).scalar_one()

    unread_conversations = (
        await db.execute(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.active.is_(True),
                Conversation.unread_count > 0,
            )
        )
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
                customer_name=conversation.customer_name,
                display_name=customer_display_name(
                    conversation.chat_id, conversation.customer_name
                ),
                state=conversation.state.value,
                last_message_preview=preview,
                last_activity_at=conversation.last_activity_at,
                unread=conversation.unread_count,
            )
        )
    return ConversationListResponse(
        items=items, total=total, unread_conversations=unread_conversations
    )


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
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
) -> StateResponse:
    conversation = await _get_conversation(db, conversation_id, tenant_id)
    takeover_service.takeover(conversation)
    # One of the two actions a staff seat is *meant* to take, so this is not
    # about catching anybody: it is so that "who was handling this customer at
    # four o'clock" has an answer (teardown X8).
    await audit.record(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="conversation_taken_over",
        target=str(conversation_id),
    )
    return StateResponse(state=conversation.state.value)


@router.post("/{conversation_id}/release", response_model=StateResponse)
async def release_conversation(
    conversation_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
) -> StateResponse:
    conversation = await _get_conversation(db, conversation_id, tenant_id)
    takeover_service.release(conversation)
    await audit.record(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="conversation_released",
        target=str(conversation_id),
    )
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


__all__ = ["customer_display_name", "format_phone_number", "router"]
