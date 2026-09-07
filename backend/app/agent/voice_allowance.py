"""The voice allowance and its gate (spec §1).

Voice is 54-74% of per-tenant AI cost, and until now it was ungated: any tenant
could set ``voice_reply_mode`` to ``always`` and multiply their bill. An
unlimited-voice tenant on the largest plan costs about $54 a month against $30
of revenue, which is a loss that grows with success.

**One allowance covers both directions.** Speech-to-text is roughly thirty
times cheaper than text-to-speech, so the outbound leg dominates whatever a
customer sends. Two counters would be more accurate and much harder to explain,
and "voice minutes" already means voice handled either way.

**Seconds are stored; minutes are shown.** ``usage_counters.voice_seconds``
already exists and already normalises both legs into one unit, so this diverges
from the spec's suggestion of metering in characters. Characters would have
meant a migration, a second unit for the inbound leg, and a lossy conversion in
between. Seconds convert to minutes exactly. What the spec was actually
protecting against, minutes reaching the database, still holds: nothing below
stores a minute.

**Running out degrades, it does not fail.** The rep keeps answering, by text.
A silent bot is the failure mode this codebase has already been burned by three
times, and none of them were worth a voice note.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limits import entitlement
from app.models.ops import UsageCounter
from app.models.tenant import TenantConfig

__all__ = [
    "SECONDS_PER_VOICE_MINUTE",
    "VOICE_MINUTES_KEY",
    "VOICE_QUOTA_NOTICE",
    "VoiceAllowance",
    "period_start",
    "voice_allowance",
]

#: The one conversion between what is stored and what is displayed.
SECONDS_PER_VOICE_MINUTE = 60

VOICE_MINUTES_KEY = "monthly_voice_minutes"

#: Fallback for a tenant provisioned before the entitlement existed. Matches the
#: trial, so a missing allowance is small-but-working rather than unlimited: an
#: unbounded default would leave the cap silently off for exactly the tenants
#: nobody has looked at, which is the population it most needs to cover.
DEFAULT_VOICE_MINUTES = 5

#: Said once per period, not once per message. Explains what changed and what
#: did not, because "voice is off" reads like the rep is broken.
VOICE_QUOTA_NOTICE = (
    "I can keep answering by text. Voice replies are paused until your plan renews."
)


def period_start(now: dt.datetime) -> dt.date:
    """First day of the current billing month.

    Calendar months, matching how ``monthly_message_quota`` is already spoken
    about on the billing page. A per-tenant anniversary date would be more
    correct once subscriptions exist and is a change to make there, in one
    place, rather than a second notion of "this month" invented here.
    """
    return now.date().replace(day=1)


@dataclass(frozen=True, slots=True)
class VoiceAllowance:
    """What a tenant has used this period, and what it may use."""

    used_seconds: int
    allowed_seconds: int

    @property
    def used_minutes(self) -> int:
        """Rounded up: a tenant who has used 61 seconds has used 2 minutes of
        their allowance, and showing 1 would make the bar disagree with the gate."""
        return -(-self.used_seconds // SECONDS_PER_VOICE_MINUTE)

    @property
    def allowed_minutes(self) -> int:
        return self.allowed_seconds // SECONDS_PER_VOICE_MINUTE

    @property
    def exhausted(self) -> bool:
        return self.used_seconds >= self.allowed_seconds

    @property
    def remaining_seconds(self) -> int:
        return max(0, self.allowed_seconds - self.used_seconds)

    @property
    def ratio(self) -> float:
        """0.0 to 1.0, clamped. Drives the meter, so it must not exceed 1 for a
        tenant grandfathered above a lowered allowance."""
        if self.allowed_seconds <= 0:
            return 1.0
        return min(1.0, self.used_seconds / self.allowed_seconds)

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "used_minutes": self.used_minutes,
            "allowed_minutes": self.allowed_minutes,
            "used_seconds": self.used_seconds,
            "allowed_seconds": self.allowed_seconds,
            "exhausted": self.exhausted,
        }


async def voice_allowance(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    now: dt.datetime | None = None,
    tenant_config: TenantConfig | None = None,
) -> VoiceAllowance:
    """Voice used this billing period, against what the plan allows.

    ``tenant_config`` is optional so the pipeline, which already holds one, does
    not pay for a second query on the hot path.
    """
    now = now or dt.datetime.now(dt.UTC)
    start = period_start(now)

    used = (
        await db.execute(
            select(func.coalesce(func.sum(UsageCounter.voice_seconds), 0)).where(
                UsageCounter.tenant_id == tenant_id,
                UsageCounter.day >= start,
            )
        )
    ).scalar_one()

    entitlements = (
        tenant_config.entitlements
        if tenant_config is not None
        else (
            await db.execute(
                select(TenantConfig.entitlements).where(TenantConfig.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
    )
    minutes = entitlement(entitlements, VOICE_MINUTES_KEY, DEFAULT_VOICE_MINUTES)

    return VoiceAllowance(
        used_seconds=int(used or 0),
        allowed_seconds=minutes * SECONDS_PER_VOICE_MINUTE,
    )
