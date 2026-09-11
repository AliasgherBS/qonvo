"""Tenants, users, membership, per-tenant config, and audit log (DESIGN.md §11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # Billing lifecycle: "trial" (self-serve signup) → "paid" (or admin-created).
    # trial_ends_at is the cutoff after which a trial tenant is gated (§9 billing);
    # NULL means no trial limit (admin-provisioned or paid).
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="trial")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Account-level on/off for the rep (spec §3). Deliberately NOT the
    # per-conversation takeover states (bot_active / paused_by_owner /
    # needs_human): that machinery is per conversation and works. This is a
    # different question, asked once for the whole workspace.
    #
    # Defaults to False, which is the point. Until now a new tenant scanned the
    # QR code and the rep began answering real customers from an empty
    # knowledge base, which nobody agreed to and is the worst possible first
    # impression of the product. Existing tenants are switched on by the
    # migration, since they already consented by using it.
    #
    # A model default is not a default when the caller always supplies the
    # field, so signup sets this explicitly too.
    rep_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Global identity — may belong to several tenants via ``tenant_users``."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_qonvo_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: Whether this address has been proven to belong to whoever holds the
    #: account. Load-bearing rather than informational: the Google sign-in path
    #: resolves accounts by email, so without this a stranger can pre-register
    #: somebody else's address and inherit their workspace (teardown X2).
    #:
    #: ``default=False`` is a real default here, unlike ``warmup_stage`` -- the
    #: two callers that create users (provision_tenant and accept_invitation)
    #: both set it explicitly, and both are tested for it.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Fernet-encrypted TOTP secret, and whether it is in force (teardown X4).
    #:
    #: Encrypted because it is a credential: whoever holds it can generate
    #: valid codes forever. Stored on ``users`` rather than somewhere
    #: admin-specific because the mechanism is not admin-specific -- the login
    #: path requires a code from anybody who has enrolled.
    #:
    #: Two columns rather than one nullable secret, so a half-finished
    #: enrolment (secret issued, first code never confirmed) cannot lock
    #: somebody out of their own account.
    totp_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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


class TeamInvitation(Base, TenantScopedMixin):
    """A pending invite for someone to join a tenant as owner/staff.

    Tenant-scoped (RLS). The raw ``token`` goes in the invite link; accepting it
    creates (or reuses) the ``User`` and a ``tenant_users`` membership. Single-use:
    once accepted or revoked it no longer resolves.
    """

    __tablename__ = "team_invitations"
    __table_args__ = (UniqueConstraint("token", name="uq_team_invitation_token"),)

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="staff")
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending → accepted | revoked
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    #: The tenant's own clock, and the only one (teardown B1/N1/V2).
    #:
    #: Opening hours used to carry their own timezone inside the
    #: ``business_hours`` JSON, and bookings used a third value on the Google
    #: Calendar integration. Both silently meant UTC, and the calendar one was
    #: unreachable for a tenant with no Google account. One field, read by the
    #: business-hours gate, the booking skills and the calendar client.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    business_hours: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    escalation_rules: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    owner_alert_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entitlements: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    debounce_window_seconds: Mapped[float | None] = mapped_column(nullable=True)
    # Business's own receiving account details, shared verbatim by the
    # ``share_payment_details`` skill when a customer wants to pay (§7). Free text
    # (bank name/title/number/IBAN, JazzCash/Easypaisa, etc.) — never card data.
    payment_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Where this business wants its billing notices sent (teardown Z7).
    #:
    #: A business's accounts department is usually not the person who signed
    #: up, and until now every billing email went to whoever created the
    #: account. NULL/empty means "use the owner's login address", which is the
    #: old behaviour and the right default: a tenant that never fills this in
    #: must keep receiving its invoices.
    #:
    #: Deliberately not accompanied by a tax id or a company address. Which of
    #: those apply depends on the jurisdiction and on the merchant of record
    #: that issues the invoice, and a field we collect but never print on
    #: anything is worse than no field.
    billing_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    #: Bumped on every write, and required to match on a write that supplies it
    #: (audit H4). Two simultaneous PUTs both returned 200 and the second
    #: silently discarded the first person's edit.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Optimistic locking, enforced by the database rather than by a check in the
    # handler (audit H4). SQLAlchemy appends `AND version = :old` to every UPDATE
    # of this row and bumps the column itself, so two writers who both read
    # version 1 produce one UPDATE that matches a row and one that matches none.
    #
    # A Python-side comparison cannot do this and was tried first: both requests
    # read version 1, both passed the check, and both returned 200 -- exactly the
    # read-then-write window the seat race (H2) has, for the same reason.
    __mapper_args__ = {"version_id_col": version}


class AuditLog(Base, TenantScopedMixin):
    """Audit trail for tenant/ops actions (DESIGN.md §8, §9)."""

    __tablename__ = "audit_log"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
