"""tenants.rep_active: an account-level on/off for the rep (spec §3)

A new tenant used to scan the QR code and have its rep start answering real
customers from an empty knowledge base. Nobody agreed to that, and it is the
worst possible first impression of the product. New tenants now start off.

Existing tenants must stay **on**. They are already live, and they consented by
using the product; switching them off on deploy would silence working
workspaces, which is a worse failure than the one this fixes.

The backfill is DDL rather than DML, deliberately. ``ADD COLUMN ... DEFAULT
TRUE`` fills existing rows as part of the ALTER and then the default is changed
to FALSE, so one pair of statements both preserves live tenants and starts new
ones off.

An ``UPDATE tenants SET rep_active = TRUE`` would work today, because the
migration role is a superuser and superusers bypass row security including
FORCE. It would stop working the moment migrations run as a non-superuser
owner, which is what the three-role design in CLAUDE.md is heading towards:
``tenants`` has FORCE ROW LEVEL SECURITY with a policy of ``id =
current_setting('app.tenant_id')``, FORCE applies to the owner, and no GUC is
set during a migration. The DDL form does not care either way, and the cost of
being wrong here is every existing tenant going silent on deploy.

Guarded with IF NOT EXISTS: 0001 builds the schema with create_all from the
current models, so on a fresh database this column already exists by the time
this migration runs. An unguarded add_column is what broke `alembic upgrade
head` on every fresh database once before.

Revision ID: 0009_rep_activation
Revises: 0008_billing
"""

from __future__ import annotations

from alembic import op

revision: str = "0009_rep_activation"
down_revision: str | None = "0008_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DEFAULT TRUE here is the backfill: existing rows are filled by the ALTER,
    # which is not subject to row security regardless of who runs it. Do not
    # "simplify" this into an UPDATE.
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
        "rep_active BOOLEAN NOT NULL DEFAULT TRUE"
    )
    # From here on, new tenants start off and activate deliberately.
    op.execute("ALTER TABLE tenants ALTER COLUMN rep_active SET DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS rep_active")
