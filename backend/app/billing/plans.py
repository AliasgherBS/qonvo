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
#:
#: The four allowances bound four different resources, and the reasons differ
#: enough that copying one shape onto another would price it wrongly.
#:
#: ``monthly_message_quota`` is the headline number and the per-reply cost.
#:
#: ``monthly_voice_minutes`` is the expensive one. Voice is 54-74% of
#: per-tenant AI cost, and one allowance covers both directions: speech-to-text
#: is roughly 30x cheaper than text-to-speech, so the outbound leg dominates
#: whatever a customer sends, and two numbers would be more accurate and much
#: harder to explain.
#:
#: ``knowledge_chars`` is deliberately generous. Retrieval means only the
#: relevant chunks ever reach a prompt, so a large corpus costs storage and a
#: one-off embedding. It never makes a reply more expensive, which is exactly
#: what a per-turn cap would wrongly imply.
#:
#: ``knowledge_upload_bytes`` is deliberately not. Raw files are kept after
#: ingestion so re-ingestion stays possible, so this is real disk on a single
#: VPS, and it is the number that stops one tenant filling it.
PLANS: dict[str, Plan] = {
    TRIAL_PLAN: Plan(
        key=TRIAL_PLAN,
        name="Trial",
        entitlements={
            "monthly_message_quota": 300,
            "monthly_voice_minutes": 5,
            "seats": 2,
            "knowledge_sources": 50,
            "knowledge_chars": 2_000_000,
            "knowledge_upload_bytes": 50 * 1024 * 1024,
        },
    ),
    "starter": Plan(
        key="starter",
        name="Starter",
        entitlements={
            "monthly_message_quota": 1_000,
            "monthly_voice_minutes": 5,
            "seats": 2,
            "knowledge_sources": 50,
            "knowledge_chars": 2_000_000,
            "knowledge_upload_bytes": 50 * 1024 * 1024,
        },
    ),
    "growth": Plan(
        key="growth",
        name="Growth",
        entitlements={
            "monthly_message_quota": 5_000,
            "monthly_voice_minutes": 20,
            "seats": 5,
            "knowledge_sources": 150,
            "knowledge_chars": 5_000_000,
            "knowledge_upload_bytes": 150 * 1024 * 1024,
        },
    ),
    "scale": Plan(
        key="scale",
        name="Scale",
        entitlements={
            "monthly_message_quota": 20_000,
            "monthly_voice_minutes": 100,
            "seats": 15,
            "knowledge_sources": 400,
            "knowledge_chars": 15_000_000,
            "knowledge_upload_bytes": 500 * 1024 * 1024,
        },
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
