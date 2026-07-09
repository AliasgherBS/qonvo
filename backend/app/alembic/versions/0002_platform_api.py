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

import sqlalchemy as sa

from alembic import op

revision: str = "0002_platform_api"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- conversations: takeover TTL + unread inbox counter (§5.5, §10) ---
    op.add_column(
        "conversations",
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "unread_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("conversations", "unread_count", server_default=None)

    # --- tenant_config: dashboard config API fields (§10 Settings) ---
    op.add_column("tenant_config", sa.Column("business_name", sa.String(255), nullable=True))
    op.add_column("tenant_config", sa.Column("custom_instructions", sa.String(), nullable=True))
    op.add_column("tenant_config", sa.Column("llm_provider", sa.String(64), nullable=True))
    op.add_column("tenant_config", sa.Column("llm_model", sa.String(128), nullable=True))

    # --- knowledge_sources: inline content + ingestion status (§6) ---
    op.add_column("knowledge_sources", sa.Column("content", sa.Text(), nullable=True))
    op.add_column(
        "knowledge_sources",
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending_ingest",
        ),
    )
    op.alter_column("knowledge_sources", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge_sources", "status")
    op.drop_column("knowledge_sources", "content")
    op.drop_column("tenant_config", "llm_model")
    op.drop_column("tenant_config", "llm_provider")
    op.drop_column("tenant_config", "custom_instructions")
    op.drop_column("tenant_config", "business_name")
    op.drop_column("conversations", "unread_count")
    op.drop_column("conversations", "paused_until")
