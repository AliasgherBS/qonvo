"""initial schema: pgvector extension, all tables, and RLS policies

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-09

Creates the pgvector extension, every table from ``app.models`` (via the shared
metadata), and enables Row-Level Security with ``tenant_id`` policies on all
tenant-scoped tables (DESIGN.md §3, §11).

RLS notes:
- ``FORCE ROW LEVEL SECURITY`` is set so policies apply even to the table owner
  (the role the app connects as) — otherwise a single-role deployment would
  silently bypass isolation.
- Trusted cross-tenant paths (scheduler, webhook session lookup) connect as the
  ``qonvo_system`` role, which carries Postgres's native ``BYPASSRLS`` attribute
  (created in scripts/postgres-init/01-app-role.sh). Deliberately NO GUC-based
  bypass in the policies: any session can set_config() an arbitrary GUC, which
  would let tenant-scoped code (or an injection) widen its own visibility.
- ``current_setting(..., true)`` (missing_ok) is used so a session that never set
  the variable yields NULL (→ zero rows) instead of erroring.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models import TENANT_SCOPED_TABLES, Base

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enable_rls(table: str, column: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    # NULLIF(..., '') because an unset custom GUC yields '' (not NULL) once any
    # transaction on the pooled connection has SET LOCAL it before — and
    # ''::uuid errors. NULL comparison → zero rows, which is the safe default.
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" FOR ALL '
        f"USING ({column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        f"WITH CHECK ({column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create all tables/enums/indexes from the SQLAlchemy metadata.
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # tenants is keyed on its own id; every other tenant-scoped table on tenant_id.
    _enable_rls("tenants", "id")
    for table in TENANT_SCOPED_TABLES:
        _enable_rls(table, "tenant_id")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "tenants"')
    for table in TENANT_SCOPED_TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    op.execute("DROP EXTENSION IF EXISTS vector")
