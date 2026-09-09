"""Who is allowed to see our cost of goods (teardown Y3).

The owner's analytics page carried an "AI cost" tile: our unit cost, to the
cent, in front of a business paying a monthly fee. It is precise and honest and
it invites exactly one question, which is a margin conversation nobody wanted
to have on the analytics page. Internally the same number is vital, so it stays
in the ops console.

Nothing enforced that split, which is why it was possible in the first place.
These are the tests that would have caught it: the figure must not be rendered
to an owner, must still be rendered to an admin, and must still be returned by
the API, because the decision was "stop showing it", not "stop measuring it".

The dashboard files are read rather than rendered. There is no JS test runner in
this repo, and a grep of the source is enough for the question being asked --
"does this page print the cost" -- while a browser test would be the only other
way to ask it. Precedent: tests/test_input_caps.py, tests/test_revocation.py.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OWNER_PAGE = REPO / "dashboard" / "app" / "(dashboard)" / "analytics" / "page.tsx"
ADMIN_PAGE = REPO / "dashboard" / "app" / "(dashboard)" / "admin" / "usage" / "page.tsx"
ANALYTICS_API = Path(__file__).resolve().parents[1] / "app" / "api" / "analytics.py"


def _code_only(source: str) -> str:
    """The file with its comments removed.

    Necessary rather than fussy: the reason the tile is gone is written in a
    comment directly above the array it was removed from, so a naive grep for
    "cost" matches the explanation and the test can never fail.
    """
    without_blocks = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return "\n".join(
        line for line in without_blocks.splitlines() if not line.strip().startswith("//")
    )


def test_the_owner_page_does_not_render_the_cost():
    code = _code_only(OWNER_PAGE.read_text())

    # The field itself, and the currency formatter that existed only to print
    # it. Either one coming back is the tile coming back.
    assert "t.cost" not in code
    assert "totals.cost" not in code
    assert "currency" not in code.lower(), "a currency formatter is back on the owner's page"


def test_the_admin_console_still_shows_it():
    """The other half of the decision. "Hide it from owners" is only correct if
    somebody can still see it, and the manual invoicing path is priced from
    this table."""
    code = _code_only(ADMIN_PAGE.read_text())

    assert "row.cost" in code
    assert "Cost" in code  # the column header


def test_the_api_still_returns_it():
    """Deliberate: this endpoint is the tenant's own usage data rather than a
    secret, and totals is documented as an open dictionary of numbers, so
    deleting a key would break clients for nothing. The fix for "the owner
    should not see this" is not to show it."""
    source = ANALYTICS_API.read_text()

    assert '"cost": round(cost, 4)' in source


def test_cost_is_still_recorded_and_priced():
    """The guard against over-correcting. Billing and the admin rollup both
    depend on the column and on compute_cost, so a change that removed the
    measurement along with the tile would break invoicing silently."""
    from app.models.ops import UsageCounter
    from app.workers.pipeline import compute_cost

    assert hasattr(UsageCounter, "cost")
    assert callable(compute_cost)
