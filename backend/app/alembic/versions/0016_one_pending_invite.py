"""One pending invite per email, enforced by the database (audit H2).

Two identical invitations fired concurrently both returned 201, and the plan's
two seats became three:

    seats: used 3 of 2 | state: over | remaining: 0
    third invite -> 402 "No seats left on your plan."

The gate then correctly refused the next one, which caps the damage at one seat
per race -- but on a fifteen-seat plan an impatient user can repeat it, and a
double submit is exactly the shape this takes.

The application counts seats, then inserts. Between those two statements a
second request can count the same number and insert too, and no amount of
care in the handler closes a window that exists because the check and the write
are separate. Only a constraint the database evaluates at write time does.

Partial, on ``status = 'pending'``: an email that was invited, accepted, and
later invited again is ordinary, and only one *live* invitation per address is
the rule the code was already trying to keep by revoking priors.

Lower-cased, because Alice@example.com and alice@example.com are one mailbox
and the race does not care about capitalisation.

Revision ID: 0016_one_pending_invite
Revises: 0015_purge_tombstoned_chunks
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0016_one_pending_invite"
down_revision: str | None = "0015_purge_tombstoned_chunks"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_team_invitation_pending_email"


def upgrade() -> None:
    bind = op.get_bind()

    # The index cannot be created while duplicates exist, and at least one
    # environment has them: production carries a pair of qa-race@example.com
    # invitations left by the audit that found this.
    #
    # Keeps the most recent and revokes the rest rather than deleting them. The
    # newest token is the one most likely to have just been emailed, and
    # revoking preserves the record that an invitation was sent -- a migration
    # that deletes rows to make an index fit is a migration that loses evidence.
    bind.execute(
        sa.text(
            """
            UPDATE team_invitations SET status = 'revoked'
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY tenant_id, lower(email)
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                    FROM team_invitations
                    WHERE status = 'pending'
                ) ranked
                WHERE ranked.rn > 1
            )
            """
        )
    )

    # checkfirst by hand: CREATE INDEX has no such flag through op.create_index,
    # and this project has been bitten before by a migration that assumed a
    # fresh database (0001 builds the schema with create_all from the current
    # models, so anything already present collides).
    inspector = sa.inspect(bind)
    existing = {ix["name"] for ix in inspector.get_indexes("team_invitations")}
    if INDEX_NAME not in existing:
        op.execute(
            sa.text(
                f"CREATE UNIQUE INDEX {INDEX_NAME} "
                "ON team_invitations (tenant_id, lower(email)) "
                "WHERE status = 'pending'"
            )
        )


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))
