"""Conversations and messages (DESIGN.md §5, §11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin
from app.db.types import JSONBType
from app.models.enums import (
    ConversationState,
    MessageAuthor,
    MessageDirection,
    MessageType,
)


class Conversation(Base, TenantScopedMixin):
    __tablename__ = "conversations"
    # Only one *active* conversation may exist per (session, chat); closed ones are
    # retained. Enforced with a partial unique index (§5.4).
    __table_args__ = (
        Index(
            "uq_active_conversation",
            "session_id",
            "chat_id",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("whatsapp_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[ConversationState] = mapped_column(
        Enum(ConversationState, name="conversation_state"),
        nullable=False,
        default=ConversationState.bot_active,
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ``active`` participates in the unique constraint so only one open conversation
    # exists per (session, chat) while historical ones are retained (§5.4).
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    human_last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Message(Base, TenantScopedMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("wa_message_id", name="uq_message_wa_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # WAHA message id; nullable for bot/human outbound not yet acked. Unique when set.
    wa_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction"),
        nullable=False,
    )
    author: Mapped[MessageAuthor] = mapped_column(
        Enum(MessageAuthor, name="message_author"),
        nullable=False,
    )
    type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type"),
        nullable=False,
        default=MessageType.text,
    )
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    wa_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
