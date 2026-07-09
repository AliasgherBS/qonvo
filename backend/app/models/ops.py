"""Notifications, analytics events, usage counters, and the DLQ (DESIGN.md §11, §12, §13)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
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
from app.models.enums import NotificationType


class Notification(Base, TenantScopedMixin):
    __tablename__ = "notifications"

    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class AnalyticsEvent(Base, TenantScopedMixin):
    __tablename__ = "analytics_events"

    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class UsageCounter(Base, TenantScopedMixin):
    """Per-tenant per-day usage rollup for metering/invoicing (DESIGN.md §13)."""

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "day", name="uq_usage_counter_day"),)

    day: Mapped[date] = mapped_column(Date, nullable=False)
    messages_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    messages_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    voice_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)


class FailedJob(Base, TenantScopedMixin):
    """Dead-letter queue for jobs that exhausted retries (DESIGN.md §5.3)."""

    __tablename__ = "failed_jobs"

    job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    function: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
