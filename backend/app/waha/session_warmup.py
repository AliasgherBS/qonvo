"""New-number warm-up schedule (DESIGN.md §5.6).

A brand-new WhatsApp number that immediately starts answering at full volume is
the classic ban pattern. The spec is week 1 capped at 50/day, week 2 at 150/day,
then normal -- ``effective_daily_cap`` already applies those ceilings, and this
module is what actually moves a session through them.

The policy is a pure function so it can be tested without a database or a clock,
mirroring :mod:`app.waha.session_recovery`; :func:`advance_warmup_stages` is the
IO around it, run daily by the scheduler.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.logging import logger
from app.core.tenancy import system_session
from app.models.whatsapp import WhatsAppSession

#: Stage 1 ends after this long, stage 2 after twice it.
WARMUP_WEEK = timedelta(days=7)

#: Terminal stage: a number that is done warming, or one an operator cleared.
NORMAL_STAGE = 0


def next_warmup_stage(
    stage: int, connected_at: datetime, *, now: datetime | None = None
) -> int | None:
    """The stage this session should move to, or ``None`` to leave it alone.

    Progression is one-way (1 → 2 → 0). Stage 0 is never revisited: it is both
    the finished state and the value an operator sets to exempt an established
    number, and ageing must not undo that.

    ``connected_at`` is the session row's creation time -- the row is written
    when the owner starts the connect flow, so it is within minutes of the scan.
    """
    if stage not in (1, 2):
        return None

    now = now or datetime.now(UTC)
    age = now - connected_at

    if age >= 2 * WARMUP_WEEK:
        # Covers a session that missed ticks: it catches up in one step rather
        # than needing one tick per week.
        return NORMAL_STAGE
    if stage == 1 and age >= WARMUP_WEEK:
        return 2
    return None


async def advance_warmup_stages() -> dict[str, int]:
    """Move every warming session to its due stage. Returns a count per stage."""
    moved: dict[str, int] = {}
    now = datetime.now(UTC)

    async with system_session() as db:
        rows = (
            await db.execute(
                select(WhatsAppSession).where(WhatsAppSession.warmup_stage.in_((1, 2)))
            )
        ).scalars()

        for row in rows:
            target = next_warmup_stage(row.warmup_stage, row.created_at, now=now)
            if target is None:
                continue
            logger.bind(session=row.session_name, was=row.warmup_stage, now=target).info(
                "warm-up stage advanced"
            )
            row.warmup_stage = target
            moved[str(target)] = moved.get(str(target), 0) + 1

        await db.commit()

    return moved
