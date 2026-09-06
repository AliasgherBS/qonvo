"""The trial terms are decided in Python and quoted in TypeScript.

The clock lives in ``auth.TRIAL_DAYS`` and the allowance in the trial plan's
``monthly_message_quota``. Neither is reachable from a Next.js component, so
``dashboard/lib/plan.ts`` mirrors them for copy.

A mirror drifts unless something checks it, and the drift is invisible: the
build passes, the tests pass, and the marketing page quietly promises a trial
the backend does not give. These tests are that check, and they are here rather
than in the dashboard suite because **the Python side is the source of truth** --
a test that lived next to the copy would be asserting the mirror against itself.

The second half enforces the rule that makes the mirror worth having: no file
outside ``plan.ts`` writes the numbers as a literal.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.billing.plans import PLANS, TRIAL_PLAN
from app.services.auth import TRIAL_DAYS

REPO = Path(__file__).resolve().parents[2]
DASHBOARD = REPO / "dashboard"
PLAN_TS = DASHBOARD / "lib" / "plan.ts"
LLMS_TXT = DASHBOARD / "public" / "llms.txt"

#: Directories whose copy a customer can read.
COPY_DIRS = [DASHBOARD / "app", DASHBOARD / "components", DASHBOARD / "lib"]

TRIAL_QUOTA = int(PLANS[TRIAL_PLAN].entitlements["monthly_message_quota"])


def _ts_const(name: str) -> int:
    """Read a numeric export out of plan.ts without a JS runtime."""
    source = PLAN_TS.read_text(encoding="utf-8")
    match = re.search(rf"export const {name}\s*=\s*(\d+)\s*;", source)
    assert match, f"{name} not found in {PLAN_TS.relative_to(REPO)}"
    return int(match.group(1))


# --- the mirror matches its source --------------------------------------------- #
def test_dashboard_trial_days_matches_the_backend():
    assert _ts_const("TRIAL_DAYS") == TRIAL_DAYS, (
        "dashboard/lib/plan.ts and auth.TRIAL_DAYS disagree about how long the "
        "trial runs. The backend decides; update the mirror."
    )


def test_dashboard_trial_quota_matches_the_plan_catalogue():
    assert _ts_const("TRIAL_MESSAGE_QUOTA") == TRIAL_QUOTA, (
        "dashboard/lib/plan.ts and plans.py disagree about the trial allowance. "
        "The catalogue decides; update the mirror."
    )


def test_llms_txt_quotes_the_real_terms():
    """llms.txt is static and cannot import, so it is checked rather than
    generated. It is the file AI search engines quote, which makes a wrong
    number there more durable than one on a page."""
    text = LLMS_TXT.read_text(encoding="utf-8")

    assert f"{TRIAL_DAYS} days" in text, f"llms.txt does not say '{TRIAL_DAYS} days'"
    assert f"{TRIAL_QUOTA}" in text, f"llms.txt does not say '{TRIAL_QUOTA}'"


# --- nobody retypes the numbers ------------------------------------------------ #
def _copy_files() -> list[Path]:
    files: list[Path] = []
    for directory in COPY_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.suffix in {".ts", ".tsx"} and "node_modules" not in path.parts:
                files.append(path)
    return sorted(files)


#: Ways the trial length shows up in prose. Deliberately narrow: a bare "14"
#: appears in dates, sizes and class names, so matching it would train everyone
#: to ignore this test.
_LITERAL_PATTERNS = [
    re.compile(rf"\b{TRIAL_DAYS}[\s‑-]?days?\b", re.IGNORECASE),
    re.compile(rf"\b{TRIAL_DAYS}-day\b", re.IGNORECASE),
    re.compile(rf"\b{TRIAL_QUOTA}\s+(customer\s+)?messages\b", re.IGNORECASE),
]


@pytest.mark.parametrize("pattern", _LITERAL_PATTERNS, ids=lambda p: p.pattern)
def test_trial_terms_are_never_retyped_in_copy(pattern):
    """Before plan.ts existed the trial was spelled out in five components.
    Changing the clock would have left four of them lying to customers, with
    nothing failing anywhere."""
    offenders = [
        f"{path.relative_to(REPO)}:{i}"
        for path in _copy_files()
        if path != PLAN_TS
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert not offenders, (
        "the trial terms are written out as a literal here: "
        + ", ".join(offenders)
        + ". Import from lib/plan.ts instead."
    )
