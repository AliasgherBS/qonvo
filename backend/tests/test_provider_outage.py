"""A provider outage must be visible to the owner and survivable for the customer.

Before this, a 429 or an outage surfaced only as `job exhausted retries, writing
DLQ row` in the worker log. The owner got nothing. The customer got nothing at
all -- indistinguishable, from their side, from the business having shut down.
The existing quota_exceeded reply covers the tenant's own entitlement quota, not
provider failures.
"""

from __future__ import annotations

from app.agent.outage import PROVIDER_OUTAGE_REPLY, should_alert_owner


class _Redis:
    """Redis with the one operation the dedupe uses."""

    def __init__(self, first: bool = True) -> None:
        self.first = first
        self.calls: list[tuple[str, int]] = []

    async def set(self, key, _value, nx=False, ex=None):
        self.calls.append((key, ex))
        return self.first


async def test_the_first_outage_of_the_day_alerts_the_owner():
    redis = _Redis(first=True)

    assert await should_alert_owner(redis, tenant_id="t1", cause="llm") is True
    assert redis.calls[0][1] == 86_400, "the alert should dedupe for a day"


async def test_the_same_cause_does_not_alert_again_that_day():
    """Every conversation hitting the same outage would otherwise fire an alert,
    which is how a real notification becomes noise the owner learns to ignore."""
    redis = _Redis(first=False)

    assert await should_alert_owner(redis, tenant_id="t1", cause="llm") is False


async def test_causes_are_deduped_separately():
    redis = _Redis(first=True)
    await should_alert_owner(redis, tenant_id="t1", cause="llm")
    await should_alert_owner(redis, tenant_id="t1", cause="stt")

    keys = [k for k, _ in redis.calls]
    assert keys[0] != keys[1], "an STT outage must not be hidden by an LLM one"


async def test_tenants_are_deduped_separately():
    redis = _Redis(first=True)
    await should_alert_owner(redis, tenant_id="t1", cause="llm")
    await should_alert_owner(redis, tenant_id="t2", cause="llm")

    keys = [k for k, _ in redis.calls]
    assert keys[0] != keys[1], "one tenant's alert must not suppress another's"


async def test_a_broken_redis_still_lets_the_alert_through():
    """Failing closed here would mean an outage during a Redis problem is
    silent twice over. Better a duplicate alert than none."""

    class _Broken:
        async def set(self, *_a, **_k):
            raise RuntimeError("redis down")

    assert await should_alert_owner(_Broken(), tenant_id="t1", cause="llm") is True


def test_the_customer_reply_does_not_leak_the_cause():
    """The customer should not read '429' or the provider's name -- it is not
    their problem and it is not their business's fault."""
    text = PROVIDER_OUTAGE_REPLY.lower()

    for leak in ("429", "openai", "gemini", "groq", "quota", "api", "token"):
        assert leak not in text
    assert len(PROVIDER_OUTAGE_REPLY) > 20
