"""The two windows behind every figure on the analytics page (teardown Y2).

The page compares a trailing window against the one before it. If the windows
overlap, are different lengths, or leave a day out, every percentage on the
page is wrong and nothing on the screen says so -- which is why this is tested
as arithmetic rather than through a request.
"""

from __future__ import annotations

import datetime as dt

import pytest
from app.api.analytics import windows

TODAY = dt.date(2026, 9, 8)


@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
def test_the_current_window_is_days_long_counting_today(days: int):
    start, _ = windows(days, TODAY)
    assert (TODAY - start).days + 1 == days


@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
def test_the_previous_window_is_the_same_length(days: int):
    start, prev_start = windows(days, TODAY)
    prev_end = start - dt.timedelta(days=1)  # inclusive
    assert (prev_end - prev_start).days + 1 == days


@pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
def test_the_windows_are_contiguous_and_do_not_overlap(days: int):
    """A day counted twice inflates both figures; a day counted in neither
    quietly deletes traffic from the comparison."""
    start, prev_start = windows(days, TODAY)
    assert prev_start < start
    assert prev_start + dt.timedelta(days=days) == start


def test_a_thirty_day_window_lands_where_it_should():
    """The parametrised properties would also hold for an off-by-one pair, so
    one case is pinned by hand."""
    assert windows(30, TODAY) == (dt.date(2026, 8, 10), dt.date(2026, 7, 11))


def test_a_single_day_window_compares_against_yesterday():
    assert windows(1, TODAY) == (TODAY, dt.date(2026, 9, 7))
