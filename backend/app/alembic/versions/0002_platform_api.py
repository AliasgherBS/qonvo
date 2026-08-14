"""platform API columns: takeover, tenant_config, knowledge status

Revision ID: 0002_platform_api
Revises: 0001_initial
Create Date: 2026-07-09

Phase 1B (platform API) column additions (DESIGN.md §5.5, §10, §6, §11):
- ``conversations``: ``paused_until`` (auto-resume TTL) + ``unread_count`` (inbox).
- ``tenant_config``: ``business_name``, ``custom_instructions``, flat
  ``llm_provider`` / ``llm_model`` for the dashboard config API.
- ``knowledge_sources``: inline ``content`` + ingestion ``status``.

No new tables are introduced, so the RLS policies from 0001 already cover every
affected table (all are tenant-scoped and were created with FORCE ROW LEVEL
SECURITY). Password storage reuses the existing ``users.hashed_password`` column
and its unique ``email`` index from 0001 — no change needed here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_platform_api"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These columns are also present in the shared SQLAlchemy metadata, so a
    # fresh install where 0001 ran ``Base.metadata.create_all`` already has them.
    # Guard every statement with IF NOT EXISTS so this historical increment is a
    # no-op on a fresh DB yet still applies to a legacy 0001-era schema, in both
    # cases advancing alembic_version to this revision.

    # --- conversations: takeover TTL + unread inbox counter (§5.5, §10) ---
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
        "paused_until TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
        "unread_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE conversations ALTER COLUMN unread_count DROP DEFAULT")

    # --- tenant_config: dashboard config API fields (§10 Settings) ---
    op.execute("ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS business_name VARCHAR(255)")
    op.execute("ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS custom_instructions VARCHAR")
    op.execute("ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(64)")
    op.execute("ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS llm_model VARCHAR(128)")

    # --- knowledge_sources: inline content + ingestion status (§6) ---
    op.execute("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS content TEXT")
    op.execute(
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS "
        "status VARCHAR(32) NOT NULL DEFAULT 'pending_ingest'"
    )
    op.execute("ALTER TABLE knowledge_sources ALTER COLUMN status DROP DEFAULT")


def downgrade() -> None:
    op.drop_column("knowledge_sources", "status")
    op.drop_column("knowledge_sources", "content")
    op.drop_column("tenant_config", "llm_model")
    op.drop_column("tenant_config", "llm_provider")
    op.drop_column("tenant_config", "custom_instructions")
    op.drop_column("tenant_config", "business_name")
    op.drop_column("conversations", "unread_count")
    op.drop_column("conversations", "paused_until")
