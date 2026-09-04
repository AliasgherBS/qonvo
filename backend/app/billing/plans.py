"""Plan catalogue (billing design §3.1).

A plan is a contract about *entitlements*, so it lives in git where it is
reviewable and testable. Prices deliberately do not appear here: Qonvo sells
through a merchant of record, which owns pricing, tax and dunning, and provider
price ids map onto these keys through ``settings.billing_price_map``.

``tenant_config.entitlements`` is what the pipeline reads at runtime, but it is
*derived* from this table by ``app.billing.service.apply_plan`` — otherwise a
plan change leaves a stale quota behind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TRIAL_PLAN = "trial"


@dataclass(frozen=True, slots=True)
class Plan:
    key: str
    name: str
    entitlements: dict[str, Any]


#: Ordered by quota: this is the order an upgrade page renders.
PLANS: dict[str, Plan] = {
    TRIAL_PLAN: Plan(
        key=TRIAL_PLAN,
        name="Trial",
        entitlements={"monthly_message_quota": 300, "seats": 2},
    ),
    "starter": Plan(
        key="starter",
        name="Starter",
        entitlements={"monthly_message_quota": 1_000, "seats": 2},
    ),
    "growth": Plan(
        key="growth",
        name="Growth",
        entitlements={"monthly_message_quota": 5_000, "seats": 5},
    ),
    "scale": Plan(
        key="scale",
        name="Scale",
        entitlements={"monthly_message_quota": 20_000, "seats": 15},
    ),
}


def get_plan(key: str) -> Plan:
    """Look up a plan, raising ``KeyError`` for anything not in the catalogue."""
    return PLANS[key]


def plan_for_price_id(price_id: str) -> Plan | None:
    """Map a provider's price id onto a plan, or None if it is not ours."""
    from app.core.config import settings

    key = (settings.billing_price_map or {}).get(price_id)
    return PLANS.get(key) if key else None


__all__ = ["PLANS", "TRIAL_PLAN", "Plan", "get_plan", "plan_for_price_id"]
