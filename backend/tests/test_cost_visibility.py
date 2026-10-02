"""Who is allowed to see our cost of goods (teardown Y3).

The owner's analytics page carried an "AI cost" tile: our unit cost, to the
cent, in front of a business paying a monthly fee. It is precise and honest and
it invites exactly one question, which is a margin conversation nobody wanted
to have on the analytics page. Internally the same number is vital, so it stays
in the ops console.

Nothing enforced that split, which is why it was possible in the first place.
These are the tests that would have caught it: the figure must not reach an
owner, must still be rendered to an admin, and must still be measured, because
the decision was "stop showing it", not "stop measuring it".

**Amended 2026-09-12.** That first pass only removed the tile. The API kept
returning ``cost`` on the deliberate grounds that this endpoint is the tenant's
own usage data rather than a secret -- which left the number one devtools panel
away from the customer it was being kept from. Hiding a figure in the client is
not hiding it. The rule is now "stop sending it", and the assertion below is
inverted from what it used to be: it holds the endpoint to withholding the key
rather than to returning it.

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


def _python_code_only(source: str) -> str:
    """The same idea for the API module, and needed for the same reason: the
    comment explaining why there is no cost key says the words "cost" key."""
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
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


def test_the_api_does_not_return_it():
    """The half of the fix that was missing.

    Only the tile was removed, so ``/api/analytics/summary`` went on serving
    ``totals.cost`` and a ``cost`` on every day in the series. A tenant who
    opened the network tab -- or anyone writing against the API, which is the
    same JSON -- could read our unit cost on their own account. The figure is
    withheld where it is produced now, not where it is displayed.

    Asserted against the source rather than a live response for the reason in
    the module docstring. Comments are stripped first, because the comment
    recording this decision names the key it is about.
    """
    code = _python_code_only(ANALYTICS_API.read_text())

    assert '"cost"' not in code, "a cost key is back in the analytics response"


def test_cost_is_still_recorded_and_priced():
    """The guard against over-correcting. Billing and the admin rollup both
    depend on the column and on compute_cost, so a change that removed the
    measurement along with the tile would break invoicing silently."""
    from app.models.ops import UsageCounter
    from app.workers.pipeline import compute_cost

    assert hasattr(UsageCounter, "cost")
    assert callable(compute_cost)
