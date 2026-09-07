"""Making a provider outage visible instead of silent.

When the LLM, STT or TTS provider fails — a 429, a timeout, an outage — the job
exhausts its retries and writes a DLQ row. That row is real, but it is only
visible in the worker log. The owner learns nothing, and the customer gets
silence, which from their side is indistinguishable from the business having
shut down. The only diagnosis path was `docker compose logs`.

This module holds the two pieces that fix that: a customer-facing reply that
says something honest without leaking the cause, and the once-a-day-per-cause
dedupe for the owner alert. The dedupe matters as much as the alert: every
conversation hitting the same outage would otherwise fire a notification, which
is how a real signal becomes noise the owner learns to ignore. Same shape as
the Google re-auth alert in app/integrations/resolver.py.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import logger

#: Sent to the customer when the AI could not be reached at all. Deliberately
#: says nothing about quotas, providers or status codes: that is not the
#: customer's problem, and naming it makes the business look broken rather than
#: busy. It also promises a human rather than a retry, because we do not know
#: how long the outage will last.
PROVIDER_OUTAGE_REPLY = (
    "Sorry, I can't reply properly right now. I've let the team know and "
    "someone will get back to you shortly."
)

#: How long one cause stays deduped for one tenant.
ALERT_TTL_SECONDS = 86_400


async def should_alert_owner(redis: Any, *, tenant_id: str, cause: str) -> bool:
    """True at most once per day, per tenant, per cause.

    Fails open. If Redis is unreachable the alert goes out anyway: an outage
    that happens during a Redis problem would otherwise be silent twice over,
    and a duplicate notification is a much smaller harm than none.
    """
    key = f"provider:outage_alert:{tenant_id}:{cause}"
    try:
        return bool(await redis.set(key, "1", nx=True, ex=ALERT_TTL_SECONDS))
    except Exception as exc:  # noqa: BLE001 — see the fail-open note above
        logger.bind(tenant_id=tenant_id, cause=cause).warning(
            f"outage-alert dedupe unavailable, alerting anyway: {exc}"
        )
        return True


__all__ = ["ALERT_TTL_SECONDS", "PROVIDER_OUTAGE_REPLY", "should_alert_owner"]
