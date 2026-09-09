"""tenant_config.timezone: one clock for the whole tenant (teardown B1, N1, V2)

Two settings governed time and both silently meant UTC.

``business_hours.timezone`` was sent by the client as the literal string
``"UTC"`` and no component anywhere was bound to the field, so it could not be
changed. The worker converts local time against it, so an owner who turned
opening hours on got a rep that refused to talk to customers during business
hours -- and only then, which is why nobody noticed.

The calendar timezone was a different field, on the integration rather than the
config, defaulting the same way. A customer booking "3 PM tomorrow" got an
event at 8 PM Karachi time on the owner's real calendar, with a confirmation
message saying three o'clock. Availability read the same clock, so the rep also
offered slots the owner was not free in.

The teardown's own preferred fix, and the one taken here: set it once and have
both places read it. That also fixes the cause rather than the symptom, which
was that the single setting governing opening hours and bookings lived inside
an optional Google integration, where a tenant with no Google account could not
reach it at all.

**Two statements, deliberately.** ``ADD COLUMN ... DEFAULT 'UTC'`` fills every
existing row as DDL, which is not subject to row security whoever runs it. The
``UPDATE`` after it only promotes a timezone somebody had actually managed to
set, and it is the one part relying on the migration role being a superuser
(see the corrected note in CLAUDE.md). If that ever stops being true the UPDATE
matches nothing and every tenant keeps ``UTC``, which is exactly the behaviour
this replaces -- so the failure mode is "no improvement", not "broken".

Nothing to promote on this deployment, checked before writing it: one tenant
has ``business_hours.timezone = "UTC"`` with hours disabled, one has ``{}``, and
the calendar integration says ``UTC``. The statement is here for deployments
where somebody had edited the JSON by hand.

Revision ID: 0011_tenant_timezone
Revises: 0010_email_verification
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_tenant_timezone"
down_revision: str | None = "0010_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS "
        "timezone VARCHAR(64) NOT NULL DEFAULT 'UTC'"
    )
    # Promote an existing setting rather than discarding it. Prefer the opening
    # hours value, since that is the one an owner could plausibly have reached;
    # fall back to the calendar integration's.
    op.execute(
        """
        UPDATE tenant_config AS tc
        SET timezone = COALESCE(
            NULLIF(tc.business_hours->>'timezone', 'UTC'),
            NULLIF((
                SELECT i.config->>'timezone'
                FROM integrations AS i
                WHERE i.tenant_id = tc.tenant_id
                  AND i.provider = 'google_calendar'
                LIMIT 1
            ), 'UTC')
        )
        WHERE COALESCE(
            NULLIF(tc.business_hours->>'timezone', 'UTC'),
            NULLIF((
                SELECT i.config->>'timezone'
                FROM integrations AS i
                WHERE i.tenant_id = tc.tenant_id
                  AND i.provider = 'google_calendar'
                LIMIT 1
            ), 'UTC')
        ) IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_config DROP COLUMN IF EXISTS timezone")
