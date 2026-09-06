"""Caps on what a tenant can put in (spec §2).

Two shapes of limit, and they fail for different reasons.

Prompt fields are billed on **every turn**, so the cap is small and fixed: no
plan makes a 50,000-character instruction a good idea, it just makes it
expensive and makes the answers worse, because the real rules drown.

Knowledge is billed at ingestion and stored forever, so it scales by plan and
is checked twice: once at the API, once in the worker. The worker check is not
belt-and-braces. A URL source has no size at all until it has been fetched.
"""

from __future__ import annotations

import pydantic
import pytest
from app.api.config import ConfigUpdateRequest
from app.api.knowledge import CreateSourceRequest, UpdateSourceRequest
from app.api.knowledge_limits import KnowledgeUsage
from app.billing.plans import PLANS, TRIAL_PLAN
from app.core.limits import (
    KNOWLEDGE_CHARS_KEY,
    KNOWLEDGE_SOURCES_KEY,
    MAX_CUSTOM_INSTRUCTIONS,
    MAX_PAYMENT_DETAILS,
    MAX_PERSONA,
    MAX_TEXT_ENTRY_CHARS,
    MAX_UPLOAD_BYTES,
    entitlement,
    exceeded,
)


# --- the error message ---------------------------------------------------------- #
def test_the_message_names_the_limit_and_the_current_value():
    """"Too long" makes someone binary-search their own paragraph."""
    err = exceeded("Custom instructions", limit=2_000, actual=3_140)

    assert str(err) == "Custom instructions is limited to 2,000 characters. This is 3,140."
    assert err.limit == 2_000
    assert err.actual == 3_140


# --- prompt fields -------------------------------------------------------------- #
@pytest.mark.parametrize(
    "field,cap",
    [
        ("custom_instructions", MAX_CUSTOM_INSTRUCTIONS),
        ("persona", MAX_PERSONA),
        ("payment_details", MAX_PAYMENT_DETAILS),
    ],
)
def test_prompt_fields_are_capped(field, cap):
    with pytest.raises(pydantic.ValidationError) as err:
        ConfigUpdateRequest(**{field: "x" * (cap + 1)})

    message = err.value.errors()[0]["msg"]
    assert f"{cap:,}" in message
    assert f"{cap + 1:,}" in message


@pytest.mark.parametrize(
    "field,cap",
    [
        ("custom_instructions", MAX_CUSTOM_INSTRUCTIONS),
        ("persona", MAX_PERSONA),
        ("payment_details", MAX_PAYMENT_DETAILS),
    ],
)
def test_exactly_at_the_cap_is_allowed(field, cap):
    """Off-by-one here means telling someone 2,000 is the limit and refusing
    2,000."""
    request = ConfigUpdateRequest(**{field: "x" * cap})
    assert len(getattr(request, field)) == cap


def test_nothing_is_silently_truncated():
    """A shortened instruction set is worse than a refused one: the save looks
    like it worked and the rep quietly stops following the rules that got cut."""
    text = "x" * (MAX_CUSTOM_INSTRUCTIONS - 1)
    assert ConfigUpdateRequest(custom_instructions=text).custom_instructions == text


def test_an_existing_oversized_value_is_grandfathered():
    """Enforce on write, not on read. A tenant already over a newly-lowered cap
    keeps working; a field they never touch is never validated, because
    exclude_unset means it is never sent."""
    request = ConfigUpdateRequest(business_name="Glow Salon")

    assert "custom_instructions" not in request.model_dump(exclude_unset=True)


# --- knowledge entries ---------------------------------------------------------- #
@pytest.mark.parametrize("model", [CreateSourceRequest, UpdateSourceRequest])
def test_one_pasted_entry_is_capped(model):
    kwargs = {"content": "x" * (MAX_TEXT_ENTRY_CHARS + 1)}
    if model is CreateSourceRequest:
        kwargs |= {"type": "manual", "title": "Prices"}

    with pytest.raises(pydantic.ValidationError) as err:
        model(**kwargs)

    assert f"{MAX_TEXT_ENTRY_CHARS:,}" in err.value.errors()[0]["msg"]


def test_the_upload_cap_is_a_memory_bound_not_only_a_cost_one():
    """`await file.read()` pulls the whole upload into the API process before
    anything can object, so this number is what stands between one request and
    the container."""
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024


# --- per-plan allowances -------------------------------------------------------- #
def test_every_plan_carries_both_knowledge_entitlements():
    for key, plan in PLANS.items():
        assert KNOWLEDGE_SOURCES_KEY in plan.entitlements, key
        assert KNOWLEDGE_CHARS_KEY in plan.entitlements, key


def test_allowances_never_shrink_as_plans_get_bigger():
    """The catalogue is ordered by quota, so a larger plan offering less
    knowledge would be a typo nobody would notice from reading the table."""
    ordered = [p for k, p in PLANS.items() if k != TRIAL_PLAN]
    for smaller, larger in zip(ordered, ordered[1:], strict=False):
        assert (
            larger.entitlements[KNOWLEDGE_SOURCES_KEY]
            >= smaller.entitlements[KNOWLEDGE_SOURCES_KEY]
        )
        assert larger.entitlements[KNOWLEDGE_CHARS_KEY] >= smaller.entitlements[KNOWLEDGE_CHARS_KEY]


def test_the_trial_can_hold_a_real_price_list():
    """A trial that cannot fit the thing a business would actually upload does
    not demonstrate the product."""
    trial = PLANS[TRIAL_PLAN].entitlements
    assert trial[KNOWLEDGE_CHARS_KEY] >= 100_000
    assert trial[KNOWLEDGE_SOURCES_KEY] >= 10


# --- reading an entitlement that may not be there yet --------------------------- #
@pytest.mark.parametrize(
    "entitlements",
    [None, {}, {"seats": 2}, {KNOWLEDGE_CHARS_KEY: None}, {KNOWLEDGE_CHARS_KEY: "nonsense"}],
)
def test_a_tenant_provisioned_before_these_keys_gets_the_default(entitlements):
    """These keys are new, so every existing tenant lacks them. A missing cap
    must not become a refused upload for someone who did nothing wrong."""
    assert entitlement(entitlements, KNOWLEDGE_CHARS_KEY, 500_000) == 500_000


def test_a_real_entitlement_wins_over_the_default():
    assert entitlement({KNOWLEDGE_CHARS_KEY: 2_000_000}, KNOWLEDGE_CHARS_KEY, 500_000) == 2_000_000


# --- usage arithmetic ----------------------------------------------------------- #
def test_remaining_never_goes_negative():
    """A tenant grandfathered above a lowered cap must render as full, not as
    "-42 sources remaining"."""
    usage = KnowledgeUsage(sources=60, chars=900_000, max_sources=25, max_chars=500_000)

    assert usage.sources_remaining == 0
    assert usage.chars_remaining == 0


# --- what a write is actually charged ------------------------------------------- #
# check_room_for decides whether a write fits. Its subtlety is `replacing_chars`:
# an edit is charged only the delta, so shrinking a source is never refused for
# exceeding a total the edit itself reduces.
async def _room(monkeypatch, *, sources, chars, max_sources=25, max_chars=500_000, **kwargs):
    from app.api import knowledge_limits as KL

    async def fake_usage(db, tenant_id):
        return KnowledgeUsage(
            sources=sources, chars=chars, max_sources=max_sources, max_chars=max_chars
        )

    monkeypatch.setattr(KL, "usage_for", fake_usage)
    return await KL.check_room_for(None, None, **kwargs)


async def test_a_new_source_at_the_source_cap_is_refused(monkeypatch):
    from app.core.limits import LimitExceeded

    with pytest.raises(LimitExceeded) as err:
        await _room(monkeypatch, sources=25, chars=0, new_source=True)

    assert "25 sources" in str(err.value)


async def test_a_new_source_below_the_cap_is_allowed(monkeypatch):
    await _room(monkeypatch, sources=24, chars=0, new_source=True)


async def test_editing_a_source_smaller_is_allowed_even_when_already_over(monkeypatch):
    """The tenant is at 600k against a 500k cap, grandfathered. Cutting a
    200k source down to 50k must not be refused: it is the fix."""
    await _room(
        monkeypatch,
        sources=10,
        chars=600_000,
        max_chars=500_000,
        added_chars=50_000,
        replacing_chars=200_000,
    )


async def test_growing_a_source_past_the_cap_is_refused(monkeypatch):
    from app.core.limits import LimitExceeded

    with pytest.raises(LimitExceeded) as err:
        await _room(
            monkeypatch,
            sources=10,
            chars=480_000,
            max_chars=500_000,
            added_chars=40_000,
            replacing_chars=10_000,
        )

    # Reports the total it would reach, not the size of the edit: 480k + 30k.
    assert "510,000" in str(err.value)


async def test_an_edit_of_the_same_size_is_free(monkeypatch):
    """Rewording a source at exactly the cap changes nothing about storage, so
    refusing it would be arithmetic getting in the way of a correction."""
    await _room(
        monkeypatch,
        sources=10,
        chars=500_000,
        max_chars=500_000,
        added_chars=20_000,
        replacing_chars=20_000,
    )


# --- the TypeScript mirror ------------------------------------------------------ #
# The counter beside a field has to know the same number the validator uses, and
# a component cannot import from Python. Same arrangement as lib/plan.ts: mirror
# it, then fail here when it drifts. Without this the drift is invisible until a
# save is refused with a number the UI said was fine.
def test_limits_ts_matches_the_python_caps():
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "dashboard" / "lib" / "limits.ts"
    ).read_text(encoding="utf-8")

    expected = {
        "MAX_CUSTOM_INSTRUCTIONS": MAX_CUSTOM_INSTRUCTIONS,
        "MAX_PERSONA": MAX_PERSONA,
        "MAX_PAYMENT_DETAILS": MAX_PAYMENT_DETAILS,
        "MAX_TEXT_ENTRY_CHARS": MAX_TEXT_ENTRY_CHARS,
    }
    for name, value in expected.items():
        found = re.search(rf"export const {name}\s*=\s*(\d+)\s*;", source)
        assert found, f"{name} missing from dashboard/lib/limits.ts"
        assert int(found.group(1)) == value, (
            f"{name}: limits.ts says {found.group(1)}, app/core/limits.py says {value}. "
            "Python decides; update the mirror."
        )

    # Written as an expression, so it is matched separately.
    found = re.search(r"export const MAX_UPLOAD_BYTES\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024", source)
    assert found, "MAX_UPLOAD_BYTES missing or not in MB form"
    assert int(found.group(1)) * 1024 * 1024 == MAX_UPLOAD_BYTES
