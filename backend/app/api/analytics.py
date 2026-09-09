"""Owner analytics — volume, cost, outcomes (DESIGN.md §9 analytics, §13).

A single ``GET /api/analytics/summary`` aggregates the data the pipeline already
records (usage counters, conversations, handoffs, leads, bookings, orders,
knowledge gaps) over a trailing window, so the dashboard needs one round-trip.

Two things were wrong for a page whose job is "is this working" (teardown Y2):

* The outcome counts ignored the window entirely. ``leads``, ``bookings``,
  ``orders`` and ``handoffs`` were lifetime totals sitting under a heading that
  said "the last 30 days", so a tenant's numbers could only ever go up and the
  range control would have changed nothing.
* There was nothing to compare them to. A figure with no previous period cannot
  answer the question the page is for, so every windowed figure now comes with
  the same measurement over the window before it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.api.knowledge import answered_gaps_subquery
from app.models.business import Booking, Handoff, Lead, Order
from app.models.conversation import Conversation
from app.models.enums import HandoffStatus
from app.models.ops import AnalyticsEvent, UsageCounter

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def windows(days: int, today: date) -> tuple[date, date]:
    """``(start, previous_start)`` for a trailing window of ``days``.

    The current window is ``[start, today]`` inclusive, so it is ``days`` long
    counting today. The previous one is the ``days`` immediately before it,
    ending the day before ``start``: contiguous, the same length, and never
    overlapping. Getting either of those wrong makes every percentage on the
    page wrong in a way nobody can see.
    """
    start = today - timedelta(days=days - 1)
    return start, start - timedelta(days=days)


def _midnight(day: date) -> datetime:
    """A date as an aware timestamp, for comparing against ``created_at``.

    ``created_at`` is ``timestamptz``; handing asyncpg a bare date to compare
    against one is how a filter turns into an error at request time.
    """
    return datetime.combine(day, time.min, tzinfo=UTC)


@router.get("/summary")
async def summary(
    days: int = Query(default=30, ge=1, le=365),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    start, prev_start = windows(days, date.today())
    start_at = _midnight(start)
    prev_start_at = _midnight(prev_start)

    # --- Usage: totals + a per-day series for the volume/cost chart ---
    usage_rows = (
        (
            await db.execute(
                select(UsageCounter)
                .where(UsageCounter.tenant_id == tenant_id, UsageCounter.day >= prev_start)
                .order_by(UsageCounter.day)
            )
        )
        .scalars()
        .all()
    )
    current_rows = [r for r in usage_rows if r.day >= start]
    previous_rows = [r for r in usage_rows if r.day < start]
    # The chart shows the selected window only. The previous window is fetched
    # in the same query because it is the same table and one round-trip, not
    # because it is drawn.
    daily = [
        {
            "day": r.day.isoformat(),
            "messages_in": r.messages_in,
            "messages_out": r.messages_out,
            "cost": float(r.cost or 0),
            "tokens": r.tokens,
        }
        for r in current_rows
    ]
    messages_in = sum(r.messages_in for r in current_rows)
    messages_out = sum(r.messages_out for r in current_rows)
    tokens = sum(r.tokens for r in current_rows)
    cost = float(sum(r.cost or 0 for r in current_rows))
    prev_messages_in = sum(r.messages_in for r in previous_rows)
    prev_messages_out = sum(r.messages_out for r in previous_rows)

    # --- Conversations by state: a snapshot, deliberately not windowed ---
    # "needs human" and "open handoffs" are questions about right now. A
    # 30-day count of them would say how many conversations *were* stuck, which
    # is not the number that gets somebody to open the inbox.
    state_rows = (
        await db.execute(
            select(Conversation.state, func.count())
            .where(Conversation.tenant_id == tenant_id)
            .group_by(Conversation.state)
        )
    ).all()
    conversation_states = {str(state): count for state, count in state_rows}

    async def _count(model, since: datetime, until: datetime | None = None) -> int:
        stmt = (
            select(func.count())
            .select_from(model)
            .where(model.tenant_id == tenant_id, model.created_at >= since)
        )
        if until is not None:
            stmt = stmt.where(model.created_at < until)
        return (await db.execute(stmt)).scalar_one()

    handoffs_open = (
        await db.execute(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.tenant_id == tenant_id, Handoff.status == HandoffStatus.open)
        )
    ).scalar_one()

    conversations = await _count(Conversation, start_at)
    leads = await _count(Lead, start_at)
    bookings = await _count(Booking, start_at)
    orders = await _count(Order, start_at)
    handoffs_total = await _count(Handoff, start_at)

    prev_conversations = await _count(Conversation, prev_start_at, start_at)
    prev_leads = await _count(Lead, prev_start_at, start_at)
    prev_bookings = await _count(Booking, prev_start_at, start_at)
    prev_orders = await _count(Order, prev_start_at, start_at)

    # --- Top unanswered questions (same aggregation as /knowledge/gaps) ---
    question = AnalyticsEvent.data["question"].astext
    answered = answered_gaps_subquery(tenant_id)
    gap_rows = (
        await db.execute(
            select(question.label("question"), func.count().label("count"))
            .select_from(AnalyticsEvent)
            .outerjoin(answered, answered.c.question == question)
            .where(
                AnalyticsEvent.tenant_id == tenant_id,
                AnalyticsEvent.event_type == "knowledge_gap",
                question.isnot(None),
            )
            .group_by(question, answered.c.answered_at)
            .having(
                or_(
                    answered.c.answered_at.is_(None),
                    func.max(AnalyticsEvent.occurred_at) > answered.c.answered_at,
                )
            )
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    top_gaps = [{"question": r.question, "count": r.count} for r in gap_rows]

    return {
        "range_days": days,
        "period_start": start.isoformat(),
        "previous_period_start": prev_start.isoformat(),
        # One flat map of figures. The previous window's are the same keys under
        # a ``prev_`` prefix rather than a parallel object, so a client that
        # treats totals as an open dictionary of numbers needs no new shape to
        # render the comparison.
        "totals": {
            "messages_in": messages_in,
            "messages_out": messages_out,
            "messages": messages_in + messages_out,
            "tokens": tokens,
            # Still returned, deliberately no longer rendered to the owner
            # (teardown Y3). This is our cost of goods, and printing it to the
            # cent for somebody paying a monthly fee invites exactly one
            # question, so the dashboard dropped the tile. It stays in the
            # response because this endpoint is the tenant's own usage data
            # rather than a secret, and because removing a key from a totals
            # map that clients treat as an open dictionary of numbers is a
            # breakage with nothing to gain: the fix for "the owner should not
            # see this" is not to show it. The ops console reads
            # ``usage_counters`` directly, so /admin/usage is unaffected either
            # way.
            "cost": round(cost, 4),
            "conversations": conversations,
            "leads": leads,
            "bookings": bookings,
            "orders": orders,
            # What the owner is paying for, added up once here rather than in
            # each client: three ways of capturing a customer, and a business
            # only ever uses one or two of them, so the individual counts are
            # mostly zeros and the sum is the figure that means something.
            "outcomes": leads + bookings + orders,
            "handoffs": handoffs_total,
            "handoffs_open": handoffs_open,
            "needs_human": conversation_states.get("needs_human", 0),
            "prev_messages_in": prev_messages_in,
            "prev_messages_out": prev_messages_out,
            "prev_messages": prev_messages_in + prev_messages_out,
            "prev_conversations": prev_conversations,
            "prev_leads": prev_leads,
            "prev_bookings": prev_bookings,
            "prev_orders": prev_orders,
            "prev_outcomes": prev_leads + prev_bookings + prev_orders,
        },
        "daily": daily,
        "conversation_states": conversation_states,
        "top_gaps": top_gaps,
    }


__all__ = ["router", "windows"]
