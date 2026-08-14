"""billing lifecycle: tenants.plan + trial_ends_at (self-serve signup)

Revision ID: 0004_billing
Revises: 0003_orders_payments
Create Date: 2026-08-14

Adds the trial/plan fields used by self-serve signup (§9). Guarded with
IF NOT EXISTS so it is a no-op on a fresh DB (where 0001's create_all already
built the columns) yet still applies to a legacy 0003-era schema.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_billing"
down_revision: str | None = "0003_orders_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan VARCHAR(32) NOT NULL DEFAULT 'trial'")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP WITH TIME ZONE")
    # Existing tenants (created before signup existed) are treated as paid so
    # they are never gated by the trial cutoff.
    op.execute("UPDATE tenants SET plan = 'paid' WHERE plan = 'trial' AND trial_ends_at IS NULL")


def downgrade() -> None:
    op.drop_column("tenants", "trial_ends_at")
    op.drop_column("tenants", "plan")
