"""Purge tombstoned knowledge chunks, which nothing read and nothing removed.

Re-ingesting a source used to mark its previous chunks ``tombstoned`` rather
than delete them. Every reader filtered them out -- retrieval
(``agent/rag.py``) and the per-source size shown to the owner
(``source_stats``) -- with one exception: ``usage_for``, the character quota,
counted every row. So refreshing a page charged the business again for text it
no longer held, for ever, and the only bound on a source's cost was how many
times it had been refreshed. Nothing purged them, so there was no way back
under the cap short of deleting the source.

Ingestion now deletes what it replaces, so nothing new accumulates. This clears
what already had.

The ``tombstoned`` column stays. Its read filters are cheap, and keeping them
means a future writer that reintroduces a soft delete cannot silently put dead
rows back into retrieval or back onto the bill.

Deliberately not batched. Nothing serves a tombstoned row, so no query blocks
on this; production held zero of them when this was written and the largest
plausible backlog is thousands, not millions.

Revision ID: 0015_purge_tombstoned_chunks
Revises: 0014_billing_email
"""

from __future__ import annotations

from alembic import op

revision: str = "0015_purge_tombstoned_chunks"
down_revision: str | None = "0014_billing_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded because 0001 builds the schema with create_all from the current
    # models: on a fresh database this table and column already exist, and on a
    # database predating the column they may not.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'knowledge_chunks' AND column_name = 'tombstoned'
            ) THEN
                DELETE FROM knowledge_chunks WHERE tombstoned = true;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Nothing to undo. The rows carried no information any reader used, and
    inventing replacements would be worse than leaving them gone."""
