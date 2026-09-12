"""Re-derive every tenant's entitlements from the plan catalogue.

Entitlements are COPIED onto the tenant when a plan is applied, not read live
from `app/billing/plans.py`. So editing the catalogue changes what new and
re-subscribing tenants get, and changes nothing at all for anyone who already
exists. That is easy to miss, because the plans endpoint and the pricing page
both read the catalogue directly and look correct while the tenants do not.

Found by checking a live tenant after shipping v0.12.0:

    monthly_voice_minutes   5      catalogue said 60
    whatsapp_numbers        MISSING
    knowledge_upload_bytes  50 MB

The missing key is the one that mattered. The number limit added in v0.12.0
reads `entitlements.get("whatsapp_numbers")` and skips the check when it is
absent, deliberately, so that a plan without the key is not accidentally capped
at zero. The consequence is that the limit enforced nothing for every tenant
that existed before it shipped, which was all of them.

Re-derives from the plan the tenant is actually on: its subscription's plan_key
where there is one, the trial otherwise. Wholesale, matching apply_plan, which
is the only thing in the codebase that writes this column -- there are no
hand-tuned entitlements to preserve.

ANY future change to plans.py needs a migration like this one, or it will
silently apply to nobody.

Revision ID: 0018_resync_entitlements
Revises: 0017_config_version
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision: str = "0018_resync_entitlements"
down_revision: str | None = "0017_config_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Imported here, not at module scope: a migration that fails to import
    # blocks every later one, and this is the only statement that needs the app.
    from app.billing.plans import PLANS, TRIAL_PLAN

    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            """
            SELECT t.id AS tenant_id, COALESCE(s.plan_key, :trial) AS plan_key
            FROM tenants t
            LEFT JOIN subscriptions s ON s.tenant_id = t.id
            """
        ),
        {"trial": TRIAL_PLAN},
    ).mappings().all()

    for row in rows:
        plan = PLANS.get(row["plan_key"]) or PLANS[TRIAL_PLAN]
        bind.execute(
            sa.text(
                """
                UPDATE tenant_config
                SET entitlements = CAST(:ents AS jsonb)
                WHERE tenant_id = :tid
                """
            ),
            {"ents": json.dumps(plan.entitlements), "tid": row["tenant_id"]},
        )


def downgrade() -> None:
    # Deliberately empty. The previous values were stale copies of an older
    # catalogue; restoring them would reintroduce the unenforced limit this
    # exists to close, and nothing reads a historical entitlement.
    pass
