"""Usage against entitlement, computed once (spec §4.3).

The owner's billing page and the admin console must show the same numbers. Two
implementations would diverge, and the admin one would be the wrong one, which
is the worst way round: the operator chasing a runaway tenant is the person
least able to notice that their screen disagrees with the customer's.

So every meter in the product comes from here, including the thresholds. "Amber
at 80%" living in two CSS files is the same bug in a cheaper disguise.

What this module deliberately does not do is decide anything. It reports. The
gates live where the consequence lives: ``is_hard_quota_exceeded`` in the
pipeline stops replies, ``voice_allowance`` pauses voice, ``check_room_for``
refuses an upload. A reporting module that also enforced would tempt someone to
enforce from a cached read.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.voice_allowance import (
    SECONDS_PER_VOICE_MINUTE,
    VOICE_MINUTES_KEY,
    period_start,
    voice_allowance,
)
from app.api.knowledge_limits import usage_for as knowledge_usage_for
from app.core.limits import entitlement
from app.models.ops import UsageCounter
from app.models.tenant import TeamInvitation, Tenant, TenantConfig, TenantUser

__all__ = ["Meter", "TenantUsage", "NEAR_LIMIT_RATIO", "tenant_usage"]

#: Where a meter turns amber. Early enough that an owner can still act: at 95%
#: the warning and the wall arrive together, which makes the warning decorative.
NEAR_LIMIT_RATIO = 0.8


@dataclass(frozen=True, slots=True)
class Meter:
    """One allowance, and what has been used of it."""

    used: int
    allowed: int

    @property
    def remaining(self) -> int:
        """Never negative. An operator can move a tenant onto a smaller plan,
        which must render as full rather than as "-42 remaining"."""
        return max(0, self.allowed - self.used)

    @property
    def ratio(self) -> float:
        if self.allowed <= 0:
            return 1.0
        return min(1.0, self.used / self.allowed)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.allowed

    @property
    def state(self) -> str:
        """``ok`` | ``near`` | ``over``.

        Computed here rather than from the ratio in each UI, so the owner's page
        and the admin console cannot disagree about when something is a problem.
        """
        if self.exhausted:
            return "over"
        if self.ratio >= NEAR_LIMIT_RATIO:
            return "near"
        return "ok"

    def as_dict(self) -> dict[str, int | str | float]:
        return {
            "used": self.used,
            "allowed": self.allowed,
            "remaining": self.remaining,
            "ratio": round(self.ratio, 4),
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class TenantUsage:
    """Every meter for one tenant, for the current period."""

    tenant_id: uuid.UUID
    plan: str
    period_start: dt.date
    period_end: dt.date
    messages: Meter
    voice_minutes: Meter
    seats: Meter
    knowledge_sources: Meter
    knowledge_chars: Meter
    knowledge_upload_mb: Meter
    trial_days_left: int | None
    rep_active: bool

    @property
    def worst_state(self) -> str:
        """The most severe meter, so a fleet view can sort by it.

        This is the number that catches a runaway tenant before the invoice
        does, which only works if one field answers "is anything wrong here".
        """
        states = [
            m.state
            for m in (
                self.messages,
                self.voice_minutes,
                self.seats,
                self.knowledge_sources,
                self.knowledge_chars,
                self.knowledge_upload_mb,
            )
        ]
        if "over" in states:
            return "over"
        if "near" in states:
            return "near"
        return "ok"

    def as_dict(self) -> dict:
        return {
            "tenant_id": str(self.tenant_id),
            "plan": self.plan,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "messages": self.messages.as_dict(),
            "voice_minutes": self.voice_minutes.as_dict(),
            "seats": self.seats.as_dict(),
            "knowledge_sources": self.knowledge_sources.as_dict(),
            "knowledge_chars": self.knowledge_chars.as_dict(),
            "knowledge_upload_mb": self.knowledge_upload_mb.as_dict(),
            "trial_days_left": self.trial_days_left,
            "rep_active": self.rep_active,
            "worst_state": self.worst_state,
        }


def _period_end(start: dt.date) -> dt.date:
    """First day of the next month: when these meters reset.

    Shown to the owner, because "1,240 / 5,000" raises the question "until
    when?" and a meter that cannot answer it invites a support message.
    """
    return (start.replace(day=28) + dt.timedelta(days=7)).replace(day=1)


async def tenant_usage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: dt.datetime | None = None,
) -> TenantUsage:
    """Every meter for one tenant. The only place these numbers are computed."""
    now = now or dt.datetime.now(dt.UTC)
    start = period_start(now)

    tenant = (
        await db.execute(
            select(Tenant.plan, Tenant.trial_ends_at, Tenant.rep_active).where(
                Tenant.id == tenant_id
            )
        )
    ).one_or_none()

    entitlements = (
        await db.execute(
            select(TenantConfig.entitlements).where(TenantConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    # Messages counted the same way the pipeline's gate counts them: inbound
    # plus outbound, from the same rollup. A meter that counted only replies
    # would show an owner half of what they are being charged for.
    messages = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(UsageCounter.messages_in + UsageCounter.messages_out), 0
                )
            ).where(UsageCounter.tenant_id == tenant_id, UsageCounter.day >= start)
        )
    ).scalar_one()

    voice = await voice_allowance(db, tenant_id, now=now)
    knowledge = await knowledge_usage_for(db, tenant_id)

    members = (
        await db.execute(
            select(func.count(TenantUser.user_id)).where(TenantUser.tenant_id == tenant_id)
        )
    ).scalar_one()
    # A pending invitation is a claimed seat, matching seats_available. Counting
    # only accepted members would let a two-seat tenant invite ten people and
    # show 1/2 while doing it.
    pending = (
        await db.execute(
            select(func.count(TeamInvitation.id)).where(
                TeamInvitation.tenant_id == tenant_id,
                TeamInvitation.status == "pending",
            )
        )
    ).scalar_one()

    trial_days_left: int | None = None
    if tenant is not None and tenant.plan == "trial" and tenant.trial_ends_at is not None:
        trial_days_left = max(0, (tenant.trial_ends_at - now).days)

    return TenantUsage(
        tenant_id=tenant_id,
        plan=tenant.plan if tenant is not None else "trial",
        period_start=start,
        period_end=_period_end(start),
        messages=Meter(
            used=int(messages or 0),
            allowed=entitlement(entitlements, "monthly_message_quota", 300),
        ),
        voice_minutes=Meter(
            used=voice.used_minutes,
            allowed=entitlement(entitlements, VOICE_MINUTES_KEY, 5),
        ),
        seats=Meter(
            used=int(members or 0) + int(pending or 0),
            allowed=entitlement(entitlements, "seats", 2),
        ),
        knowledge_sources=Meter(used=knowledge.sources, allowed=knowledge.max_sources),
        knowledge_chars=Meter(used=knowledge.chars, allowed=knowledge.max_chars),
        # Megabytes, not bytes. The number is for a person, and "52,428,800 of
        # 52,428,800" is not a sentence anybody reads correctly.
        knowledge_upload_mb=Meter(
            used=knowledge.upload_bytes // (1024 * 1024),
            allowed=knowledge.max_upload_bytes // (1024 * 1024),
        ),
        trial_days_left=trial_days_left,
        rep_active=bool(tenant.rep_active) if tenant is not None else False,
    )


def voice_seconds_to_minutes(seconds: int) -> int:
    """Exposed so nothing else re-derives the conversion."""
    return -(-seconds // SECONDS_PER_VOICE_MINUTE)
