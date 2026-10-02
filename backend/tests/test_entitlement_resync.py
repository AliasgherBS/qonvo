"""0018 exists because a catalogue change reaches nobody on its own.

Entitlements are COPIED onto the tenant when a plan is applied, not read live
from plans.py. Editing the catalogue changes what new tenants get and changes
nothing for anyone who already exists -- while /api/billing/plans and the
pricing page both read the catalogue directly and look correct.

Found live after v0.12.0: every tenant in both environments was missing
`whatsapp_numbers`, and the number limit shipped in that release reads
`.get("whatsapp_numbers")` and skips when absent. It enforced nothing, for
everyone.
"""

from __future__ import annotations

import pathlib

from app.billing.plans import PLANS, TRIAL_PLAN

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app/alembic/versions/0018_resync_entitlements.py"
)


def test_the_migration_covers_every_tenant_not_only_subscribers():
    """A tenant with no subscription is on the trial, and those were the ones
    with entirely empty entitlements."""
    sql = MIGRATION.read_text()
    assert "LEFT JOIN subscriptions" in sql
    assert "COALESCE(s.plan_key, :trial)" in sql


def test_an_unknown_plan_key_falls_back_rather_than_crashing():
    """A subscription naming a plan that no longer exists must not abort a
    migration partway through the fleet."""
    assert "PLANS.get(row[" in MIGRATION.read_text()


def test_every_plan_carries_every_entitlement_key():
    """The resync is only as good as the catalogue. A plan missing a key gives
    that tenant a silently unenforced limit, which is the whole bug."""
    keys = set()
    for plan in PLANS.values():
        keys |= set(plan.entitlements)
    for key, plan in PLANS.items():
        missing = keys - set(plan.entitlements)
        assert not missing, f"{key} is missing {sorted(missing)}"


def test_the_trial_is_the_floor_for_every_allowance():
    """The fallback plan must never be the most generous one, or an unknown
    plan key becomes an upgrade."""
    trial = PLANS[TRIAL_PLAN].entitlements
    for key, plan in PLANS.items():
        if key == TRIAL_PLAN:
            continue
        for ent, value in trial.items():
            assert plan.entitlements[ent] >= value, f"{key}.{ent} is below the trial"
