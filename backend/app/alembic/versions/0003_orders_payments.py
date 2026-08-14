"""Phase 3: orders table + tenant payment details

Revision ID: 0003_orders_payments
Revises: 0002_platform_api
Create Date: 2026-07-10

Adds the ``orders`` table (captured by the ``take_order`` skill) with the same
``tenant_id`` RLS policy as every other tenant-scoped table (DESIGN.md §3, §7),
and a ``payment_details`` column on ``tenant_config`` for the
``share_payment_details`` skill.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models import Base

from alembic import op

revision: str = "0003_orders_payments"
down_revision: str | None = "0002_platform_api"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # On a fresh install 0001's ``create_all`` already built ``orders`` (and its
    # RLS policy, since it is in TENANT_SCOPED_TABLES) and the payment_details
    # column lives in the shared metadata too. Guard every statement so this
    # historical increment is a no-op on a fresh DB yet still applies to a legacy
    # 0002-era schema.

    # Create just the new orders table from the shared metadata (skip if present).
    Base.metadata.tables["orders"].create(bind=op.get_bind(), checkfirst=True)

    op.execute('ALTER TABLE "orders" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "orders" FORCE ROW LEVEL SECURITY')
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "orders"')
    op.execute(
        'CREATE POLICY tenant_isolation ON "orders" FOR ALL '
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    # The init script's ALTER DEFAULT PRIVILEGES only covers tables created by the
    # POSTGRES superuser; a table created here by the migration OWNER role does not
    # inherit them, so grant DML to the app + system roles explicitly (§3).
    # (Idempotent: re-granting an existing privilege is a no-op.)
    for role in ("qonvo_app", "qonvo_system"):
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "orders" TO {role}')

    op.execute("ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS payment_details TEXT")


def downgrade() -> None:
    op.drop_column("tenant_config", "payment_details")
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "orders"')
    op.drop_table("orders")
