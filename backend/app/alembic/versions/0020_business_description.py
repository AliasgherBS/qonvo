"""One line saying what the business does, always in the prompt.

The system prompt names the business and never said what trade it is in. The
trade lives in the knowledge, and knowledge is retrieved per turn, so a question
about something the business does NOT do retrieves nothing relevant and the rep
has no idea what it is.

Found by running four businesses through the conversation lab: asked "do you
sell car tyres?", a salon, a dental practice, a clinic and a design studio all
answered "we do not have that detail to hand, the team will confirm". The only
two that ever got it right were the two whose NAME contained their trade.

Nullable, because every existing tenant has managed without it and a blank one
simply leaves the prompt as it is today.

Revision ID: 0020_business_description
Revises: 0019_voice_seconds_in
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0020_business_description"
down_revision: str | None = "0019_voice_seconds_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded: 0001 builds the schema with create_all from the current models,
    # so on a database that has never been migrated this already exists.
    inspector = sa.inspect(op.get_bind())
    if "business_description" not in {c["name"] for c in inspector.get_columns("tenant_config")}:
        op.add_column(
            "tenant_config",
            sa.Column("business_description", sa.String(length=300), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "business_description" in {c["name"] for c in inspector.get_columns("tenant_config")}:
        op.drop_column("tenant_config", "business_description")
