"""subscriptions + billing_events (billing design §3.2)

Two tenant-scoped tables: the tenant's current plan as last reported by the
billing provider, and the ledger of provider events we have acted on (the
idempotency guard against webhook retries).

Follows 0006's shape: create from metadata (checkfirst, since a fresh DB's
create_all already built it), then enable/force RLS, add the tenant policy, and
GRANT explicitly — a table created by the migration owner does not inherit
DEFAULT PRIVILEGES.

Revision ID: 0008_billing
Revises: 0007_session_recovery
"""

from __future__ import annotations

from app.db.base import Base
from app.models import billing as _billing  # noqa: F401 — registers the tables

from alembic import op

revision: str = "0008_billing"
down_revision: str | None = "0007_session_recovery"
branch_labels = None
depends_on = None

_TABLES = ("subscriptions", "billing_events")


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        Base.metadata.tables[table].create(bind=bind, checkfirst=True)

        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" FOR ALL '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        for role in ("qonvo_app", "qonvo_system"):
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}')


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
