"""M6 from the VPS audit: numbers were unbounded and unremovable.

Eight rapid creates returned eight 201s and left eleven sessions on one tenant,
and the plan catalogue said nothing about numbers even though multiple numbers
is a paid feature on the price list. There was `logout` and `restart` and no
removal at all, so the rows could never be tidied.

Each linked number is also a WAHA session at roughly 22 MB, which
docs/CAPACITY-AND-SCALING.md identifies as the RAM ceiling of the box. So this
bounds a real resource, not only a billing line.
"""

from __future__ import annotations

import pytest
from app.billing.plans import PLANS, TRIAL_PLAN


@pytest.mark.parametrize(
    "plan_key,expected",
    [(TRIAL_PLAN, 1), ("starter", 1), ("growth", 1), ("scale", 2)],
)
def test_every_plan_bounds_its_numbers(plan_key, expected):
    assert PLANS[plan_key].entitlements["whatsapp_numbers"] == expected


def test_no_plan_leaves_numbers_unbounded():
    """An absent key means "no limit" to the check in the API, so a plan added
    later without this entitlement would silently reopen the hole."""
    missing = [k for k, p in PLANS.items() if "whatsapp_numbers" not in p.entitlements]
    assert missing == []
