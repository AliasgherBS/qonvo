"""Rate limiting on the endpoints an attacker hits repeatedly.

Argon2 already makes each guess expensive and the forgot-password route does not
reveal whether an address exists, so this is throttling rather than a hole being
closed. What it stops is the cheap version: a script trying ten thousand
passwords against one known email.

Most of these tests are about the ways a limiter hurts the wrong person. A
limiter that locks out a legitimate user is a denial of service we built
ourselves, and it is easier to ship than the attack it prevents.
"""

from __future__ import annotations

import pytest
from app.core import throttle


class FakeRedis:
    """Enough Redis to count. Records expiries so TTLs can be asserted."""

    def __init__(self, *, broken: bool = False) -> None:
        self.values: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.broken = broken

    async def incr(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis is down")
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        if self.broken:
            raise ConnectionError("redis is down")
        self.expiries[key] = seconds

    async def get(self, key: str):
        if self.broken:
            raise ConnectionError("redis is down")
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    async def delete(self, key: str) -> None:
        if self.broken:
            raise ConnectionError("redis is down")
        self.values.pop(key, None)


# --- the limit does what it says -------------------------------------------------- #
async def test_an_ip_is_allowed_up_to_the_limit_then_refused():
    redis = FakeRedis()

    for _ in range(throttle.LOGIN.limit):
        assert await throttle.check(redis, throttle.LOGIN, ip="1.2.3.4", account=None) is False

    assert await throttle.check(redis, throttle.LOGIN, ip="1.2.3.4", account=None) is True


async def test_the_window_is_set_once_not_on_every_hit():
    """Re-setting the TTL on each attempt makes the window slide forward
    forever, so a steady attacker is never released and a throttled user never
    recovers."""
    redis = FakeRedis()

    for _ in range(5):
        await throttle.check(redis, throttle.LOGIN, ip="1.2.3.4", account=None)

    [ttl] = set(redis.expiries.values())
    assert ttl == throttle.LOGIN.window_seconds
    assert len(redis.expiries) == 1  # one key, one expiry call


async def test_two_addresses_do_not_share_a_budget():
    redis = FakeRedis()

    for _ in range(throttle.LOGIN.limit + 1):
        await throttle.check(redis, throttle.LOGIN, ip="1.1.1.1", account=None)

    assert await throttle.check(redis, throttle.LOGIN, ip="2.2.2.2", account=None) is False


# --- the ways it could hurt the wrong person -------------------------------------- #
async def test_a_correct_password_never_counts_against_the_account():
    """check() reads the account counter and never increments it; only
    record_failure does. Otherwise an attacker could lock a victim out of their
    own account by failing on their behalf, which turns a login limiter into a
    denial-of-service tool aimed at our own customers."""
    redis = FakeRedis()

    for _ in range(throttle.LOGIN.limit + 5):
        await throttle.check(redis, throttle.LOGIN, ip=None, account="victim@example.com")

    account_keys = [k for k in redis.values if ":acct:" in k]
    assert account_keys == []


async def test_succeeding_forgets_the_earlier_failures():
    """Someone who mistypes nine times and then gets it right must not stay one
    mistake away from lockout for the rest of the window."""
    redis = FakeRedis()
    for _ in range(throttle.LOGIN.limit - 1):
        await throttle.record_failure(redis, throttle.LOGIN, account="user@example.com")

    await throttle.clear(redis, throttle.LOGIN, account="user@example.com")

    assert await throttle.check(redis, throttle.LOGIN, ip=None, account="user@example.com") is False


async def test_it_fails_open_when_redis_is_down():
    """An outage that also blocks sign-in turns a degraded service into an
    inaccessible one, and the endpoint behind this is still password
    protected."""
    redis = FakeRedis(broken=True)

    assert await throttle.check(redis, throttle.LOGIN, ip="1.2.3.4", account="a@b.com") is False
    # And the bookkeeping calls must not raise either.
    await throttle.record_failure(redis, throttle.LOGIN, account="a@b.com")
    await throttle.clear(redis, throttle.LOGIN, account="a@b.com")


async def test_the_limits_are_generous_enough_for_a_real_person():
    """A limit tight enough to catch a typo is a support ticket, not security."""
    assert throttle.LOGIN.limit >= 5
    assert throttle.LOGIN.window_seconds <= 60 * 60


# --- what ends up in Redis --------------------------------------------------------- #
async def test_the_email_address_is_not_the_key():
    """Redis keys show up in logs, in MONITOR output and to anyone who runs
    KEYS *. An address is personal data and a counter does not need it."""
    redis = FakeRedis()
    await throttle.record_failure(redis, throttle.LOGIN, account="Someone@Example.com")

    [key] = list(redis.values)
    assert "someone" not in key.lower()
    assert "example.com" not in key.lower()


async def test_the_same_address_hashes_the_same_however_it_is_typed():
    """Otherwise capitalising an address resets the counter, which is a bypass
    anybody would find by accident."""
    a, b = FakeRedis(), FakeRedis()
    await throttle.record_failure(a, throttle.LOGIN, account="User@Example.com ")
    await throttle.record_failure(b, throttle.LOGIN, account="user@example.com")

    assert list(a.values) == list(b.values)


async def test_different_throttles_do_not_share_a_counter():
    """A failed login must not consume somebody's password-reset budget."""
    redis = FakeRedis()
    await throttle.record_failure(redis, throttle.LOGIN, account="a@b.com")
    await throttle.record_failure(redis, throttle.PASSWORD_RESET, account="a@b.com")

    assert len(redis.values) == 2


# --- identifying the caller through a proxy ---------------------------------------- #
class FakeRequest:
    def __init__(self, headers=None, host="10.0.0.1"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()


def test_the_first_forwarded_address_is_the_client():
    """A caller can append anything to X-Forwarded-For, so trusting the last
    entry is trusting the attacker. The first is the real origin."""
    request = FakeRequest({"x-forwarded-for": "203.0.113.9, 10.0.0.1, 172.16.0.1"})

    assert throttle.client_ip(request) == "203.0.113.9"


def test_it_falls_back_to_the_socket_when_there_is_no_header():
    assert throttle.client_ip(FakeRequest(host="198.51.100.4")) == "198.51.100.4"


def test_a_blank_forwarded_header_does_not_become_a_shared_key():
    """An empty string would key every caller to the same bucket and throttle
    the whole world at once."""
    request = FakeRequest({"x-forwarded-for": "  "}, host="198.51.100.4")

    assert throttle.client_ip(request) == "198.51.100.4"


# --- the endpoints are actually wired --------------------------------------------- #
@pytest.mark.parametrize(
    "function,limit_name",
    [("login", "LOGIN"), ("signup", "SIGNUP"), ("forgot_password_route", "PASSWORD_RESET")],
)
def test_the_endpoint_uses_its_throttle(function, limit_name):
    import inspect

    from app.api import auth

    source = inspect.getsource(getattr(auth, function))
    assert f"throttle.{limit_name}" in source


def test_forgot_password_still_answers_202_when_throttled():
    """Any other response would reveal which addresses exist, which is the
    enumeration this endpoint is shaped to prevent. Throttling it must not undo
    that."""
    import inspect

    from app.api import auth

    source = inspect.getsource(auth.forgot_password_route)
    throttled = source.index("throttle.check")
    following = source[throttled : throttled + 400]

    assert 'return {"status": "ok"}' in following
    assert "429" not in following
