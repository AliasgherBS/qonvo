"""Record inbound voice duration separately from generated (analytics).

`voice_seconds` counts only what we synthesize, since 0016 made the allowance
bound generation alone. That is right for billing and useless for the question
an owner actually asks: are my customers sending voice notes, and how long are
they?

Adding the column rather than inferring it from message counts, because a
count cannot answer "how long is a typical voice note" and that is the number
that tells an owner whether voice is being used seriously or tried once.

Revision ID: 0019_voice_seconds_in
Revises: 0018_resync_entitlements
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0019_voice_seconds_in"
down_revision: str | None = "0018_resync_entitlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 builds the schema with create_all from the current models,
    # so on a database that has never been migrated this already exists.
    inspector = sa.inspect(op.get_bind())
    if "voice_seconds_in" not in {c["name"] for c in inspector.get_columns("usage_counters")}:
        op.add_column(
            "usage_counters",
            sa.Column("voice_seconds_in", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "voice_seconds_in" in {c["name"] for c in inspector.get_columns("usage_counters")}:
        op.drop_column("usage_counters", "voice_seconds_in")
