"""A version on tenant_config, so two editors cannot silently overwrite (H4).

Two simultaneous PUTs with different values both returned 200:

    tone before: "Warm, Concise, Direct"
    PUT {"tone":"RACE-AAA"}  -> 200
    PUT {"tone":"RACE-BBB"}  -> 200      (both accepted)
    tone after : "RACE-BBB"              last write wins, silently

There was no ETag, no If-Match and no version column, so the API could not tell
a fresh edit from one made against a stale copy. An owner and a staff member
both on Behavior, or one person with the page open in two tabs, and one of them
loses their work behind a success message.

Unlike the activation toggle -- where "the last person to click wins" is what
anyone would expect of a global boolean -- configuration is long-form text
somebody wrote. Losing it silently is the failure.

DEFAULT 1 rather than a backfill UPDATE: a default fills existing rows as DDL,
which does not depend on the migration role being a superuser. CLAUDE.md records
this project getting that wrong in the other direction once.

Revision ID: 0017_config_version
Revises: 0016_one_pending_invite
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0017_config_version"
down_revision: str | None = "0016_one_pending_invite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 builds the schema with create_all from the current models,
    # so on a database that has never been migrated this column already exists.
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("tenant_config")}
    if "version" not in columns:
        op.add_column(
            "tenant_config",
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("tenant_config")}
    if "version" in columns:
        op.drop_column("tenant_config", "version")
