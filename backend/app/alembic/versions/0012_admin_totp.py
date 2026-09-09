"""users.totp_secret / totp_enabled: a second factor for the admin (teardown X4)

``POST /api/admin/tenants/{id}/impersonate`` mints an owner-scoped token for
any tenant on the platform. That is a reasonable support tool and it was
audited. What guarded it was one password on one account, reachable from the
public internet at ``qonvo.org/admin``, with no second factor, no IP
restriction and no separate login surface. One phished password is every
customer's WhatsApp inbox, and the same account can delete any tenant outright.

The teardown's own note on timing is why this is a migration rather than a
plan: adding a second factor before there are many customers is a column;
adding it later is a migration for accounts that already exist and a support
burden for each one.

The columns are on ``users`` rather than on an admin-specific table, because
the mechanism is not admin-specific. Nothing here restricts it to
``is_qonvo_admin``; the login path requires a code from anybody who has enabled
one, so offering it to owners later is a UI change rather than a schema one.

``totp_secret`` is Fernet-encrypted by the application, like
``integrations.encrypted_credentials``. A TOTP secret is a credential: with it,
anybody can generate valid codes forever.

Both columns are nullable/defaulted, so this is additive and existing accounts
are unaffected until somebody enrols.

Revision ID: 0012_admin_totp
Revises: 0011_tenant_timezone
"""

from __future__ import annotations

from alembic import op

revision: str = "0012_admin_totp"
down_revision: str | None = "0011_tenant_timezone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(512)")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "totp_enabled BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_enabled")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_secret")
