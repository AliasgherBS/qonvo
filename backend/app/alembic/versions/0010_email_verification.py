"""users.email_verified: make "the address identifies the account" true (teardown X2)

There was no email verification anywhere in the password path: no token, no
mail, no column. ``email_verified`` appeared in the codebase only where a Google
``id_token`` is checked, which is correct but covers only Google.

On its own that is untidy. Combined with ``POST /api/auth/google`` resolving the
account by looking the verified Google address up with ``find_user`` and signing
into whatever row it finds, it is account pre-hijacking:

1. The attacker signs up as ``owner@theclinic.pk`` with a password only they
   know. No mail was ever sent to that address, so nobody learns of it.
2. Months later the real owner finds Qonvo and clicks Sign in with Google.
   Google asserts the address, the lookup matches the attacker's row, and the
   owner is signed into the attacker's tenant as its owner.
3. They connect their WhatsApp number, upload their price list and start
   serving customers. The attacker's password still works, and every
   conversation, customer number and the live session are theirs.

Verification is not a formality here. It is the only thing that makes "the
address identifies the account" true, and two sign-in paths already depend on
that being true.

**Existing users are grandfathered as verified.** They are real accounts that
predate the check, and the alternative is locking live workspaces out of
connecting a number to prove a point about a hole nobody walked through. Signup
sends the mail from here on.

Backfilled with ``ADD COLUMN ... DEFAULT TRUE`` then a default change, the same
idiom as 0009 and for the same reason: DDL fills existing rows as part of the
ALTER, so it neither depends on row security nor on who runs the migration. An
``UPDATE users SET email_verified = TRUE`` happens to work today only because
the migration role is a superuser.

Guarded with IF NOT EXISTS: 0001 builds the schema with create_all from the
current models, so on a fresh database this column already exists by the time
this migration runs.

Revision ID: 0010_email_verification
Revises: 0009_rep_activation
"""

from __future__ import annotations

from alembic import op

revision: str = "0010_email_verification"
down_revision: str | None = "0009_rep_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DEFAULT TRUE is the backfill for accounts that predate verification. Do
    # not "simplify" this into an UPDATE.
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "email_verified BOOLEAN NOT NULL DEFAULT TRUE"
    )
    # From here on a new account is unverified until it proves the address.
    op.execute("ALTER TABLE users ALTER COLUMN email_verified SET DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified")
