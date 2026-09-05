"""Plan catalogue and the service-entitlement decision (billing design §3.1, §3.3).

``service_state`` answers one question -- may this tenant's bot reply right now --
as a pure function, so the policy is testable without a database or a clock,
mirroring app/waha/session_recovery.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.billing.plans import PLANS, TRIAL_PLAN, get_plan
from app.billing.state import (
    BlockedReason,
    ServiceState,
    seats_available,
    service_state,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


class _Sub:
    """Stand-in for a Subscription row."""

    def __init__(self, status: str, period_end: datetime | None = None) -> None:
        self.status = status
        self.current_period_end = period_end


def _state(**overrides) -> ServiceState:
    base = {
        "tenant_status": "active",
        "plan": "trial",
        "trial_ends_at": NOW + timedelta(days=3),
        "subscription": None,
        "now": NOW,
    }
    base.update(overrides)
    return service_state(**base)


# --- catalogue -------------------------------------------------------------- #
def test_every_plan_carries_a_quota_and_seats():
    for key, plan in PLANS.items():
        assert plan.key == key
        assert plan.entitlements["monthly_message_quota"] > 0
        assert plan.entitlements["seats"] > 0


def test_the_trial_plan_matches_what_signup_grants():
    """Signup wrote 300 by hand; the catalogue must not disagree with it."""
    assert get_plan(TRIAL_PLAN).entitlements["monthly_message_quota"] == 300


def test_unknown_plan_key_is_rejected():
    with pytest.raises(KeyError):
        get_plan("enterprise-unlimited")


def test_plans_are_ordered_by_quota():
    """The catalogue order is what an upgrade page renders."""
    quotas = [p.entitlements["monthly_message_quota"] for p in PLANS.values()]
    assert quotas == sorted(quotas)


# --- suspension beats everything -------------------------------------------- #
def test_a_suspended_tenant_is_blocked_even_when_paid():
    state = _state(
        tenant_status="suspended",
        subscription=_Sub("active", NOW + timedelta(days=20)),
    )
    assert state.blocked_reason is BlockedReason.suspended


# --- legacy tenants (no subscription row) ----------------------------------- #
def test_a_live_trial_without_a_subscription_is_served():
    """Every tenant today has no subscription row; none of them may break."""
    assert _state().allowed is True


def test_an_expired_trial_without_a_subscription_is_blocked():
    state = _state(trial_ends_at=NOW - timedelta(minutes=1))
    assert state.blocked_reason is BlockedReason.trial_expired


def test_a_legacy_paid_tenant_is_served():
    """Admin-provisioned tenants carry plan=paid and no trial end."""
    assert _state(plan="paid", trial_ends_at=None).allowed is True


# --- active subscriptions ---------------------------------------------------- #
@pytest.mark.parametrize("status", ["active", "trialing"])
def test_an_active_subscription_is_served(status):
    state = _state(
        trial_ends_at=NOW - timedelta(days=30),  # long-expired trial must not matter
        subscription=_Sub(status, NOW + timedelta(days=10)),
    )
    assert state.allowed is True


# --- past due: the grace window ---------------------------------------------- #
def test_a_just_failed_payment_keeps_the_bot_answering():
    """A card that failed this morning must not silence a business today."""
    state = _state(subscription=_Sub("past_due", NOW - timedelta(days=1)))
    assert state.allowed is True


def test_past_due_blocks_once_grace_runs_out():
    state = _state(subscription=_Sub("past_due", NOW - timedelta(days=8)))
    assert state.blocked_reason is BlockedReason.past_due


def test_grace_window_length_is_configurable():
    sub = _Sub("past_due", NOW - timedelta(days=3))
    assert service_state(
        tenant_status="active",
        plan="starter",
        trial_ends_at=None,
        subscription=sub,
        now=NOW,
        grace_days=2,
    ).blocked_reason is BlockedReason.past_due


# --- cancellation: paid through the period ----------------------------------- #
def test_a_cancelled_subscription_runs_to_the_end_of_the_period():
    """They paid for the month; cancelling mid-month does not take it away."""
    state = _state(subscription=_Sub("canceled", NOW + timedelta(days=5)))
    assert state.allowed is True


def test_a_cancelled_subscription_stops_after_the_period():
    state = _state(subscription=_Sub("canceled", NOW - timedelta(minutes=1)))
    assert state.blocked_reason is BlockedReason.canceled


def test_a_cancelled_subscription_with_no_period_end_stops_now():
    assert _state(subscription=_Sub("canceled", None)).blocked_reason is BlockedReason.canceled


# --- seat entitlement -------------------------------------------------------- #
def test_seats_left_counts_members_and_pending_invites():
    """A pending invite is a claimed seat. Counting only accepted members lets a
    tenant on 2 seats invite ten people and seat them all."""
    assert seats_available({"seats": 5}, members=2, pending_invites=1) == 2


def test_no_seat_entitlement_means_unlimited():
    """Tenants predating the catalogue have no seats key; they must not be locked
    out of their own team page."""
    assert seats_available({}, members=99, pending_invites=0) is None


def test_seats_available_never_goes_negative():
    """An operator can move a tenant onto a smaller plan; existing members stay,
    but no new ones can be added."""
    assert seats_available({"seats": 2}, members=5, pending_invites=0) == 0
