"""team seats: team_invitations table

Revision ID: 0006_team_invitations
Revises: 0004_billing
Create Date: 2026-08-16

Adds the ``team_invitations`` table so an owner can invite staff/co-owners to a
tenant. Tenant-scoped with the same RLS policy as every other tenant table
(DESIGN.md §3). Follows the 0003 pattern: create from shared metadata (no-op on a
fresh DB where 0001's create_all already built it), then enable/force RLS, add the
isolation policy, and grant DML to the app + system roles explicitly (a table
created by the migration OWNER role does not inherit the init script's default
privileges).

NOTE: numbered 0006 (skipping 0005) to avoid colliding with an in-progress
``0005_personal_foundation`` on the qonvo-personal-milestone-a branch. Both chain
off 0004; whichever merges second re-parents onto the other.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Base

from alembic import op

revision: str = "0006_team_invitations"
down_revision: str | None = "0004_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.tables["team_invitations"].create(bind=op.get_bind(), checkfirst=True)

    op.execute('ALTER TABLE "team_invitations" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "team_invitations" FORCE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "team_invitations"')
    op.execute(
        'CREATE POLICY tenant_isolation ON "team_invitations" FOR ALL '
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    for role in ("qonvo_app", "qonvo_system"):
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "team_invitations" TO {role}')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "team_invitations"')
    op.drop_table("team_invitations")
