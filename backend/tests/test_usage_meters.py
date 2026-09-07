"""Usage against entitlement, computed once (spec §4.3).

The owner's billing page and the admin console read the same function. These
tests are mostly about the arithmetic at the edges, because that is where a
meter stops being reassuring and starts being wrong: a tenant grandfathered
above a lowered allowance, a plan with no allowance at all, an operator moving
someone down a tier.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.services.usage import NEAR_LIMIT_RATIO, Meter, TenantUsage, _period_end


def _usage(**overrides) -> TenantUsage:
    import uuid

    base = {
        "tenant_id": uuid.uuid4(),
        "plan": "growth",
        "period_start": dt.date(2026, 9, 1),
        "period_end": dt.date(2026, 10, 1),
        "messages": Meter(used=0, allowed=5_000),
        "voice_minutes": Meter(used=0, allowed=20),
        "seats": Meter(used=1, allowed=5),
        "knowledge_sources": Meter(used=0, allowed=150),
        "knowledge_chars": Meter(used=0, allowed=5_000_000),
        "knowledge_upload_mb": Meter(used=0, allowed=150),
        "trial_days_left": None,
        "rep_active": True,
    }
    return TenantUsage(**{**base, **overrides})


# --- the shared threshold ------------------------------------------------------- #
def test_the_threshold_leaves_room_to_act():
    """At 95% the warning and the wall arrive together, which makes the warning
    decorative."""
    assert NEAR_LIMIT_RATIO == 0.8


@pytest.mark.parametrize(
    "used,allowed,state",
    [
        (0, 100, "ok"),
        (79, 100, "ok"),
        (80, 100, "near"),
        (99, 100, "near"),
        (100, 100, "over"),
        (150, 100, "over"),
    ],
)
def test_state_is_decided_once_not_per_ui(used, allowed, state):
    """"Amber at 80%" living in two CSS files is the same divergence bug in a
    cheaper disguise."""
    assert Meter(used=used, allowed=allowed).state == state


# --- edges that would otherwise render nonsense --------------------------------- #
def test_a_grandfathered_tenant_renders_as_full_not_negative():
    """An operator can move a tenant onto a smaller plan. That freezes new
    usage; it must not print "-42 remaining" or a bar past the end."""
    meter = Meter(used=9_000, allowed=5_000)

    assert meter.remaining == 0
    assert meter.ratio == 1.0
    assert meter.state == "over"


def test_a_zero_allowance_is_over_rather_than_a_division_error():
    meter = Meter(used=0, allowed=0)

    assert meter.ratio == 1.0
    assert meter.state == "over"
    assert meter.remaining == 0


def test_exactly_at_the_allowance_is_over_not_nearly():
    """5,000 of 5,000 is spent. Calling it "near" would promise one more."""
    assert Meter(used=5_000, allowed=5_000).state == "over"


# --- the fleet ordering --------------------------------------------------------- #
def test_worst_state_reflects_any_meter():
    """The fleet view sorts by this, so it has to notice a problem in a meter
    nobody was looking at. A tenant fine on messages and full on voice is still
    a tenant to look at."""
    assert _usage().worst_state == "ok"
    assert _usage(voice_minutes=Meter(used=17, allowed=20)).worst_state == "near"
    assert _usage(knowledge_upload_mb=Meter(used=150, allowed=150)).worst_state == "over"


def test_over_outranks_near():
    usage = _usage(
        messages=Meter(used=4_500, allowed=5_000),  # near
        seats=Meter(used=5, allowed=5),  # over
    )
    assert usage.worst_state == "over"


# --- the reset date -------------------------------------------------------------- #
@pytest.mark.parametrize(
    "start,expected",
    [
        (dt.date(2026, 1, 1), dt.date(2026, 2, 1)),
        (dt.date(2026, 2, 1), dt.date(2026, 3, 1)),
        (dt.date(2026, 12, 1), dt.date(2027, 1, 1)),
        (dt.date(2028, 2, 1), dt.date(2028, 3, 1)),  # leap year
    ],
)
def test_the_reset_date_rolls_the_year_and_survives_february(start, expected):
    """"1,240 / 5,000" invites the question "until when?", and a meter that
    cannot answer it invites a support message instead."""
    assert _period_end(start) == expected


# --- serialisation --------------------------------------------------------------- #
def test_every_meter_is_serialised_for_both_surfaces():
    payload = _usage(trial_days_left=9).as_dict()

    for key in (
        "messages",
        "voice_minutes",
        "seats",
        "knowledge_sources",
        "knowledge_chars",
        "knowledge_upload_mb",
    ):
        assert set(payload[key]) == {"used", "allowed", "remaining", "ratio", "state"}, key

    # The fields a UI needs beyond the meters themselves.
    assert payload["worst_state"] == "ok"
    assert payload["trial_days_left"] == 9
    assert payload["rep_active"] is True
    assert payload["period_end"] == "2026-10-01"


def test_the_payload_is_json_serialisable():
    """It crosses the wire to two different pages."""
    import json

    payload = _usage().as_dict()
    assert json.loads(json.dumps(payload)) == payload


# --- one implementation, not two ------------------------------------------------- #
def test_both_surfaces_call_the_same_function():
    """§4.3's actual requirement. Asserted against the source because the whole
    point is that no second implementation exists to test."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "api"
    owner = (root / "billing.py").read_text(encoding="utf-8")
    admin = (root / "admin.py").read_text(encoding="utf-8")

    assert "from app.services.usage import tenant_usage" in owner
    assert "from app.services.usage import tenant_usage" in admin
    # Neither surface computes a ratio or a threshold of its own.
    for name, source in (("billing.py", owner), ("admin.py", admin)):
        assert "0.8" not in source, f"{name} has its own threshold"


def test_knowledge_chars_are_measured_from_chunks_not_source_content():
    """Found live: the fleet endpoint showed 2 sources and 0 characters against
    7,775 genuinely stored. For an uploaded file or a fetched URL,
    sources.content is NULL and the text exists only as chunks, so summing the
    source column reports zero for a real knowledge base."""
    import inspect

    from app.api import knowledge_limits

    source = inspect.getsource(knowledge_limits.usage_for)
    assert "KnowledgeChunk.content" in source
    assert "KnowledgeSource.content" not in source
