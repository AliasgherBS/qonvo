"""Skills, idempotent skill executions, and integration credentials (DESIGN.md §7)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin
from app.db.types import JSONBType


class Skill(Base, TenantScopedMixin):
    """A per-tenant enabled tool (JSON schema + handler key), gated by entitlements."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_skill_tenant_key"),)

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class SkillExecution(Base, TenantScopedMixin):
    """Idempotency ledger for write-skills (DESIGN.md §7).

    ``idempotency_key`` = ``{conversation_id}:{tool_call_id}``; handlers check for
    an existing row before executing to survive at-least-once redelivery.
    """

    __tablename__ = "skill_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_skill_exec_idempotency"),
    )

    skill_key: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    result: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class Integration(Base, TenantScopedMixin):
    """Per-tenant integration with Fernet-encrypted credentials (DESIGN.md §3, §7)."""

    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_integration_tenant_provider"),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Fernet ciphertext (see app.core.security.encrypt_secret). Never store plaintext.
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
