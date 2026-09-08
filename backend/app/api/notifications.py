"""Dashboard notification log (DESIGN.md §5.5, §10, §12.1)."""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# One label for a customer across the product, so the bell and the inbox can
# never name the same person differently (teardown I1, S4).
from app.api.conversations import customer_display_name
from app.api.deps import get_db, require_tenant
from app.models.conversation import Conversation
from app.models.ops import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# A sentence ends at ., !, ? or the Urdu full stop, followed by whitespace.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?\u06d4])\s")
_SUMMARY_MAX = 200


def first_sentence(text: str | None, *, limit: int = _SUMMARY_MAX) -> str | None:
    """The first sentence of a notification body.

    Escalation bodies are the model's ``reason`` verbatim, which ends with the
    model explaining itself to the system ("This is a complaint/refund scenario,
    which requires a human handoff") -- machine talk quoted back at the owner
    (teardown S4). The full body is still returned, so nothing is lost.
    """
    if not text:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    head = _SENTENCE_BREAK.split(collapsed, maxsplit=1)[0]
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "\u2026"
    return head


def _conversation_id_of(row: Notification) -> str | None:
    """The conversation a notification is about, when it names one.

    ``meta`` is written by whatever raised the notification (``human_handoff``
    sets ``conversation_id``); a row without one simply is not linkable.
    """
    meta = row.meta or {}
    value = meta.get("conversation_id")
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except ValueError:
        return None


def _to_dict(row: Notification, subjects: dict[str, str] | None = None) -> dict:
    conversation_id = _conversation_id_of(row)
    return {
        "id": str(row.id),
        "type": row.type.value,
        "title": row.title,
        "body": row.body,
        # The reason without the model's trailing self-justification.
        "summary": first_sentence(row.body),
        "read": row.read,
        "meta": row.meta,
        # Enough for the bell to link the whole row through to the chat, which
        # is the only thing an owner wants to do with an escalation.
        "conversation_id": conversation_id,
        "subject": (subjects or {}).get(conversation_id or ""),
        "created_at": row.created_at,
    }


async def _subjects_for(
    db: AsyncSession, tenant_id: UUID, rows: list[Notification]
) -> dict[str, str]:
    """Customer labels for every conversation these notifications point at.

    One query for the whole page rather than one per row: the bell polls every
    30 s and an owner with a busy day has a long log.
    """
    ids = {cid for cid in (_conversation_id_of(row) for row in rows) if cid}
    if not ids:
        return {}
    conversations = (
        await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.id.in_([UUID(cid) for cid in ids]),
            )
        )
    ).scalars().all()
    return {
        str(c.id): customer_display_name(c.chat_id, c.customer_name) for c in conversations
    }


@router.get("")
async def list_notifications(
    unread: bool | None = Query(default=None),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    filters = [Notification.tenant_id == tenant_id]
    if unread is not None:
        filters.append(Notification.read == (not unread))
    rows = (
        await db.execute(
            select(Notification).where(*filters).order_by(Notification.created_at.desc())
        )
    ).scalars().all()
    subjects = await _subjects_for(db, tenant_id, list(rows))
    return [_to_dict(r, subjects) for r in rows]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification not found")
    row.read = True
    await db.flush()
    return _to_dict(row, await _subjects_for(db, tenant_id, [row]))


__all__ = ["first_sentence", "router"]
