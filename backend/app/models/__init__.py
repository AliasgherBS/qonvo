"""SQLAlchemy models (DESIGN.md §11). Importing this package registers all
tables on ``Base.metadata`` — required for Alembic autogenerate and metadata
create.
"""

from __future__ import annotations

from app.db.base import Base
from app.models.billing import BillingEvent, Subscription
from app.models.business import Booking, Handoff, Lead, Order, ReminderSuppression
from app.models.conversation import Conversation, Message
from app.models.knowledge import KnowledgeChunk, KnowledgeSource
from app.models.ops import AnalyticsEvent, FailedJob, Notification, UsageCounter
from app.models.skill import Integration, Skill, SkillExecution
from app.models.tenant import (
    AuditLog,
    TeamInvitation,
    Tenant,
    TenantConfig,
    TenantUser,
    User,
)
from app.models.whatsapp import WhatsAppSession

# Tenant-scoped tables get an RLS policy keyed on ``app.tenant_id`` (via their
# ``tenant_id`` column). ``tenants`` is special-cased in the migration (keyed on
# ``id``); ``users`` is global and intentionally excluded.
TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "tenant_users",
    "tenant_config",
    "audit_log",
    "whatsapp_sessions",
    "knowledge_sources",
    "knowledge_chunks",
    "conversations",
    "messages",
    "skills",
    "skill_executions",
    "integrations",
    "team_invitations",
    "leads",
    "bookings",
    "orders",
    "reminder_suppressions",
    "handoffs",
    "notifications",
    "analytics_events",
    "usage_counters",
    "failed_jobs",
    "subscriptions",
    "billing_events",
)

__all__ = [
    "AnalyticsEvent",
    "AuditLog",
    "Base",
    "BillingEvent",
    "Booking",
    "Conversation",
    "FailedJob",
    "Handoff",
    "Integration",
    "KnowledgeChunk",
    "KnowledgeSource",
    "Lead",
    "Message",
    "Notification",
    "Order",
    "ReminderSuppression",
    "Skill",
    "Subscription",
    "SkillExecution",
    "TENANT_SCOPED_TABLES",
    "TeamInvitation",
    "Tenant",
    "TenantConfig",
    "TenantUser",
    "UsageCounter",
    "User",
    "WhatsAppSession",
]
