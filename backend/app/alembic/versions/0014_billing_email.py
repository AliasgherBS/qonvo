"""tenant_config.billing_email: send invoices where the business wants them

Teardown Z7. There was no billing address separate from the login address, so
every billing notice went to whoever happened to sign up rather than to the
person who pays the bills. For a one-person business those are the same
address; for anything with an accounts department they are not, and the
notice that matters most is the one nobody sees.

Nullable, and empty means "use the address they sign in with". That is the
honest default rather than back-filling every row with the owner's address,
which would freeze a copy of it: change the login address later and the
invoices would keep going to the old one, silently, which is the failure this
column exists to prevent.

320 characters, matching ``users.email``, because that is the longest address
RFC 5321 permits.

Additive, so no re-granting: column privileges follow the table's existing
grants to ``qonvo_app`` and ``qonvo_system``.

Revision ID: 0014_billing_email
Revises: 0013_source_last_ingested
"""

from __future__ import annotations

from alembic import op

revision: str = "0014_billing_email"
down_revision: str | None = "0013_source_last_ingested"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS billing_email VARCHAR(320)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_config DROP COLUMN IF EXISTS billing_email")
