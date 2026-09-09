"""knowledge_sources.last_ingested_at: when a source was last read successfully

Teardown K2: "a source is a name, a type and a date, and nothing else". The
table could not say when a website was last crawled, which is the question an
owner asks about a source that answers from stale prices.

``updated_at`` could not answer it. That column moves on a title edit and on
the write that records an ingestion *failure*, so it means "when did this row
last change", which is a different question and a misleading answer for the
one being asked.

Stamped by the worker only on success, so a failed re-crawl keeps the last
timestamp that was actually true rather than advancing to a moment when nothing
was read.

**NULL for existing rows, and that is the honest value** rather than an
inconvenience to be defaulted away. "Never successfully ingested" is what we
know about a source that predates the column, and back-filling it with
``created_at`` or ``now()`` would assert a crawl that may never have happened.
This is the case the 0009 note's DDL-default idiom does *not* apply to: there
the default carried real meaning for old rows, here it would invent one.

Nullable and additive, so nothing needs re-granting and no existing row is
touched.

Revision ID: 0013_source_last_ingested
Revises: 0012_admin_totp
"""

from __future__ import annotations

from alembic import op

revision: str = "0013_source_last_ingested"
down_revision: str | None = "0012_admin_totp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS "
        "last_ingested_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_sources DROP COLUMN IF EXISTS last_ingested_at")
