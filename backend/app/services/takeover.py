"""Human takeover / pause state machine (DESIGN.md §5.5).

States: ``bot_active`` -> ``paused_by_agent`` | ``paused_by_owner`` | ``needs_human``.
Used by both the conversations API (explicit take-over/release) and the webhook
ingress (implicit take-over on an owner's ``fromMe`` reply).

There is no dedicated scheduler cron for auto-resume in Phase 1 (the scheduler
lives in ``app.workers.scheduler``, out of this agent's ownership). Instead,
:func:`maybe_auto_resume` is called from the conversations API's read paths
(list/detail) so a stale pause self-heals the next time anyone looks at the
inbox, without requiring a background job.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.models.conversation import Conversation
from app.models.enums import ConversationState


def _resume_deadline(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=settings.takeover_auto_resume_ttl_seconds)


async def get_or_create_conversation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    chat_id: str,
) -> Conversation:
    """Return the active conversation for ``(session, chat)``, creating one if absent."""
    row = (
        await db.execute(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.session_id == session_id,
                Conversation.chat_id == chat_id,
                Conversation.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = Conversation(
        tenant_id=tenant_id,
        session_id=session_id,
        chat_id=chat_id,
        state=ConversationState.bot_active,
    )
    db.add(row)
    await db.flush()
    return row


def takeover(conversation: Conversation) -> Conversation:
    """Explicit (dashboard) or implicit (owner ``fromMe``) take-over.

    Both land on ``paused_by_owner`` — the API contract only distinguishes the
    *trigger* (button vs. phone reply), not the resulting state. Sets the
    auto-resume deadline from ``settings.takeover_auto_resume_ttl_seconds``.
    """
    now = datetime.now(UTC)
    conversation.state = ConversationState.paused_by_owner
    conversation.human_last_message_at = now
    conversation.paused_until = _resume_deadline(now)
    return conversation


def release(conversation: Conversation) -> Conversation:
    """Resume the bot: ``bot_active``, clearing the pause deadline."""
    conversation.state = ConversationState.bot_active
    conversation.paused_until = None
    return conversation


def is_auto_resume_due(conversation: Conversation, *, now: datetime | None = None) -> bool:
    if conversation.state == ConversationState.bot_active:
        return False
    if conversation.paused_until is None:
        return False
    now = now or datetime.now(UTC)
    return now >= conversation.paused_until


def maybe_auto_resume(conversation: Conversation, *, now: datetime | None = None) -> bool:
    """Resume the bot if the TTL has elapsed. Returns ``True`` iff it did.

    Call this from every conversation read path (list/detail) — see module
    docstring for why there is no separate cron for this in Phase 1.
    """
    if is_auto_resume_due(conversation, now=now):
        release(conversation)
        logger.bind(conversation_id=str(conversation.id)).info("auto-resumed after TTL")
        return True
    return False


async def implicit_takeover(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    chat_id: str,
) -> Conversation:
    """Owner replied from their own phone (``fromMe``) -> implicit take-over (§5.5b)."""
    conversation = await get_or_create_conversation(
        db, tenant_id=tenant_id, session_id=session_id, chat_id=chat_id
    )
    takeover(conversation)
    logger.bind(tenant_id=str(tenant_id), chat_id=chat_id).info(
        "implicit takeover: owner fromMe reply detected"
    )
    return conversation


__all__ = [
    "get_or_create_conversation",
    "implicit_takeover",
    "is_auto_resume_due",
    "maybe_auto_resume",
    "release",
    "takeover",
]
