"""Leads, bookings, reminder suppression, and handoffs (DESIGN.md §5.5, §5.7, §7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin
from app.db.types import JSONBType
from app.models.enums import BookingStatus, HandoffStatus


class Lead(Base, TenantScopedMixin):
    __tablename__ = "leads"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class Booking(Base, TenantScopedMixin):
    __tablename__ = "bookings"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status"),
        nullable=False,
        default=BookingStatus.pending,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Reminder scheduling (DESIGN.md §5.7): confirmation + 24h-before, capped at 2.
    confirmation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class ReminderSuppression(Base, TenantScopedMixin):
    """Opt-out list ("stop") for reminder recipients (DESIGN.md §5.7)."""

    __tablename__ = "reminder_suppressions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_reminder_suppression_phone"),
    )

    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Order(Base, TenantScopedMixin):
    """A customer order captured by the ``take_order`` skill (DESIGN.md §7)."""

    __tablename__ = "orders"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # [{"name": str, "quantity": int, "price": float|None}]
    items: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class Handoff(Base, TenantScopedMixin):
    __tablename__ = "handoffs"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[HandoffStatus] = mapped_column(
        Enum(HandoffStatus, name="handoff_status"),
        nullable=False,
        default=HandoffStatus.open,
    )
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
