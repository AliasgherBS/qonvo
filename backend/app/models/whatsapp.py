"""WhatsApp session ↔ tenant mapping (DESIGN.md §3, §11)."""

from __future__ import annotations

from sqlalchemy import Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin
from app.models.enums import SessionStatus


class WhatsAppSession(Base, TenantScopedMixin):
    """Maps a WAHA ``session_name`` to a tenant. A tenant may have several."""

    __tablename__ = "whatsapp_sessions"
    __table_args__ = (
        UniqueConstraint("session_name", name="uq_whatsapp_session_name"),
    )

    session_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status"),
        nullable=False,
        default=SessionStatus.stopped,
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="WEBJS")
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Per-session HMAC secret for verifying that session's webhooks.
    hmac_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    daily_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    # Warm-up stage for a new number (DESIGN.md §5.6): 1 → 50/day, 2 → 150/day, 0 → normal.
    warmup_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
