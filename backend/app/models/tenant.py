"""Tenants, users, membership, per-tenant config, and audit log (DESIGN.md §11)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import JSONBType
from app.models.enums import UserRole


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A business. ``id`` is the value bound to ``app.tenant_id`` for RLS."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Global identity — may belong to several tenants via ``tenant_users``."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_qonvo_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TenantUser(Base, TenantScopedMixin):
    """Membership of a user in a tenant with a role."""

    __tablename__ = "tenant_users"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_tenant_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.owner,
    )


class TenantConfig(Base, TenantScopedMixin):
    """Persona, providers, hours, rules, and plan entitlements (DESIGN.md §3, §13)."""

    __tablename__ = "tenant_config"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_tenant_config_tenant"),)

    persona: Mapped[str | None] = mapped_column(String, nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    languages: Mapped[list] = mapped_column(JSONBType, nullable=False, default=list)
    primary_language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    providers: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    # Flat LLM selection surfaced by the dashboard config API (DESIGN.md §10 Settings);
    # ``providers`` remains the internal per-capability provider map (§4).
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_hours: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    escalation_rules: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    owner_alert_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entitlements: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    debounce_window_seconds: Mapped[float | None] = mapped_column(nullable=True)


class AuditLog(Base, TenantScopedMixin):
    """Audit trail for tenant/ops actions (DESIGN.md §8, §9)."""

    __tablename__ = "audit_log"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
