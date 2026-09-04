"""Send-gateway pacing math and sequencing (DESIGN.md §5.6)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.waha.send_gateway import (
    WARMUP_STAGE_CAPS,
    DailyCapExceeded,
    SendGateway,
    SessionPacing,
    effective_daily_cap,
    pacing_for_session,
    token_bucket_wait,
    typing_delay_seconds,
)


# --- pure math ------------------------------------------------------------- #
def test_typing_delay_proportional():
    assert typing_delay_seconds("", per_char=0.03, max_seconds=10) == 0
    assert typing_delay_seconds("a" * 100, per_char=0.03, max_seconds=10) == pytest.approx(3.0)


def test_typing_delay_capped():
    assert typing_delay_seconds("a" * 10_000, per_char=0.03, max_seconds=10) == 10


def test_effective_daily_cap_warmup():
    assert effective_daily_cap(1, 500) == WARMUP_STAGE_CAPS[1] == 50
    assert effective_daily_cap(2, 500) == WARMUP_STAGE_CAPS[2] == 150
    assert effective_daily_cap(0, 500) == 500  # no warm-up
    assert effective_daily_cap(1, 30) == 30  # stricter of cap vs warm-up


def test_token_bucket_consumes_when_available():
    wait, tokens = token_bucket_wait(3.0, 0.0, 0.0, capacity=3, refill_seconds=5.0)
    assert wait == 0.0
    assert tokens == 2.0


def test_token_bucket_waits_when_empty():
    # No tokens, no time elapsed → must wait a full refill interval for 1 token.
    wait, tokens = token_bucket_wait(0.0, 0.0, 0.0, capacity=3, refill_seconds=5.0)
    assert wait == pytest.approx(5.0)
    assert tokens == 0.0


def test_token_bucket_refills_over_time():
    # 10s elapsed at 1 token / 5s → 2 tokens refilled, consume 1, one left.
    wait, tokens = token_bucket_wait(0.0, 0.0, 10.0, capacity=3, refill_seconds=5.0)
    assert wait == 0.0
    assert tokens == pytest.approx(1.0)


def test_token_bucket_caps_at_capacity():
    wait, tokens = token_bucket_wait(0.0, 0.0, 100.0, capacity=3, refill_seconds=5.0)
    assert wait == 0.0
    assert tokens == pytest.approx(2.0)  # filled to 3, consumed 1


# --- gateway integration (fakeredis, mocked waha/sleep) -------------------- #
def _gateway(fake_redis):
    waha = AsyncMock()
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    gw = SendGateway(
        waha,
        fake_redis,
        sleep=fake_sleep,
        now=lambda: 0.0,
        jitter=lambda a, b: (a + b) / 2,  # deterministic mid-point
    )
    return gw, waha, slept


async def test_send_text_sequence(fake_redis):
    gw, waha, slept = _gateway(fake_redis)
    await gw.send_text("s1", "1@c.us", "hello", pacing=SessionPacing())

    # Human-like sequence: seen → startTyping → (delay) → sendText → stopTyping.
    waha.send_seen.assert_awaited_once_with("s1", "1@c.us")
    waha.start_typing.assert_awaited_once_with("s1", "1@c.us")
    waha.send_text.assert_awaited_once()
    waha.stop_typing.assert_awaited_once_with("s1", "1@c.us")
    # A typing delay proportional to the 5-char message was slept.
    assert any(s > 0 for s in slept)


async def test_daily_cap_enforced(fake_redis):
    gw, waha, _ = _gateway(fake_redis)
    pacing = SessionPacing(daily_cap=2, burst=10)
    await gw.send_text("s1", "1@c.us", "a", pacing=pacing)
    await gw.send_text("s1", "1@c.us", "b", pacing=pacing)
    with pytest.raises(DailyCapExceeded):
        await gw.send_text("s1", "1@c.us", "c", pacing=pacing)
    assert waha.send_text.await_count == 2


async def test_burst_then_throttle(fake_redis):
    gw, waha, slept = _gateway(fake_redis)
    pacing = SessionPacing(daily_cap=100, burst=3, min_delay=4, max_delay=6)
    # Burst of 3 consumes tokens without a pacing wait (now is fixed at 0).
    for _ in range(3):
        await gw.send_text("s1", "1@c.us", "x", pacing=pacing)
    pacing_waits = [s for s in slept if s == pytest.approx(5.0)]
    assert pacing_waits == []
    # 4th send finds an empty bucket and must wait ~one refill interval (jitter mid = 5).
    await gw.send_text("s1", "1@c.us", "x", pacing=pacing)
    assert any(s == pytest.approx(5.0) for s in slept)


# --- pacing from the session row ------------------------------------------- #
def test_pacing_for_session_uses_the_row_not_defaults():
    """The tenant's configured cap and warm-up stage must reach the limiter.

    Bot replies used to construct a bare ``SessionPacing()``, so every automated
    reply was paced at the dataclass defaults (500/day, no warm-up) regardless of
    what the session was configured for. Manual replies and reminders always
    built pacing from the row; only the bot -- the bulk of the traffic -- did not.
    """

    class _Row:
        daily_cap = 40
        warmup_stage = 2

    pacing = pacing_for_session(_Row())

    assert pacing.daily_cap == 40
    assert pacing.warmup_stage == 2
