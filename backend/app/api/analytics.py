"""Owner analytics — volume, cost, outcomes (DESIGN.md §9 analytics, §13).

A single ``GET /api/analytics/summary`` aggregates the data the pipeline already
records (usage counters, conversations, handoffs, leads, bookings, orders,
knowledge gaps) over a trailing window, so the dashboard needs one round-trip.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.business import Booking, Handoff, Lead, Order
from app.models.conversation import Conversation
from app.models.enums import HandoffStatus
from app.models.ops import AnalyticsEvent, UsageCounter

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary")
async def summary(
    days: int = Query(default=30, ge=1, le=365),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    start = date.today() - timedelta(days=days - 1)

    # --- Usage: totals + a per-day series for the volume/cost chart ---
    usage_rows = (
        (
            await db.execute(
                select(UsageCounter)
                .where(UsageCounter.tenant_id == tenant_id, UsageCounter.day >= start)
                .order_by(UsageCounter.day)
            )
        )
        .scalars()
        .all()
    )
    daily = [
        {
            "day": r.day.isoformat(),
            "messages_in": r.messages_in,
            "messages_out": r.messages_out,
            "cost": float(r.cost or 0),
            "tokens": r.tokens,
        }
        for r in usage_rows
    ]
    messages_in = sum(r.messages_in for r in usage_rows)
    messages_out = sum(r.messages_out for r in usage_rows)
    tokens = sum(r.tokens for r in usage_rows)
    cost = float(sum(r.cost or 0 for r in usage_rows))

    # --- Conversations by state ---
    state_rows = (
        await db.execute(
            select(Conversation.state, func.count())
            .where(Conversation.tenant_id == tenant_id)
            .group_by(Conversation.state)
        )
    ).all()
    conversation_states = {str(state): count for state, count in state_rows}
    conversations_total = sum(conversation_states.values())

    async def _count(model) -> int:
        return (
            await db.execute(
                select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
            )
        ).scalar_one()

    handoffs_open = (
        await db.execute(
            select(func.count())
            .select_from(Handoff)
            .where(Handoff.tenant_id == tenant_id, Handoff.status == HandoffStatus.open)
        )
    ).scalar_one()

    leads = await _count(Lead)
    bookings = await _count(Booking)
    orders = await _count(Order)
    handoffs_total = await _count(Handoff)

    # --- Top unanswered questions (same aggregation as /knowledge/gaps) ---
    question = AnalyticsEvent.data["question"].astext
    gap_rows = (
        await db.execute(
            select(question.label("question"), func.count().label("count"))
            .where(
                AnalyticsEvent.tenant_id == tenant_id,
                AnalyticsEvent.event_type == "knowledge_gap",
                question.isnot(None),
            )
            .group_by(question)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    top_gaps = [{"question": r.question, "count": r.count} for r in gap_rows]

    return {
        "range_days": days,
        "totals": {
            "messages_in": messages_in,
            "messages_out": messages_out,
            "messages": messages_in + messages_out,
            "tokens": tokens,
            "cost": round(cost, 4),
            "conversations": conversations_total,
            "leads": leads,
            "bookings": bookings,
            "orders": orders,
            "handoffs": handoffs_total,
            "handoffs_open": handoffs_open,
            "needs_human": conversation_states.get("needs_human", 0),
        },
        "daily": daily,
        "conversation_states": conversation_states,
        "top_gaps": top_gaps,
    }


__all__ = ["router"]
