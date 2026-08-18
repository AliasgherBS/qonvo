"""session auto-recovery bookkeeping on whatsapp_sessions

Adds the two columns the recovery poller needs to bound its attempts:
how many restarts it has tried this failure episode, and when it last tried.

Revision ID: 0007_session_recovery
Revises: 0006_team_invitations
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0007_session_recovery"
down_revision: str | None = "0006_team_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_sessions",
        sa.Column(
            "recovery_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "whatsapp_sessions",
        sa.Column("last_recovery_at", sa.DateTime(timezone=True), nullable=True),
    )

    # A table altered by the migration owner does not hand new privileges to
    # the app roles automatically, and DEFAULT PRIVILEGES do not apply to a
    # superuser-owned object. Existing grants are column-agnostic so this is
    # belt-and-braces, but omitting it is how 0003 nearly shipped a table the
    # app role could not read.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_sessions "
        "TO qonvo_app, qonvo_system"
    )


def downgrade() -> None:
    op.drop_column("whatsapp_sessions", "last_recovery_at")
    op.drop_column("whatsapp_sessions", "recovery_attempts")
