"""Rate limiting for the endpoints an attacker hits repeatedly (audit §Open).

Argon2 already makes each password guess expensive, and the forgot-password
route deliberately does not reveal whether an address exists, so this is
throttling rather than a hole being closed. What it stops is the cheap version
of the attack: a script trying ten thousand passwords against one known email,
or walking a list of addresses to see which ones are worth attacking.

**Two keys per attempt, not one.** Per-IP alone is defeated by a botnet, and
per-account alone lets one attacker lock a victim out by failing on purpose.
Limiting both means neither is a single point of failure, and the account
counter only counts *failures*, so a legitimate user is never locked out by
somebody else's guessing.

Fixed windows, following ``agent.debounce.is_rate_limited``, which is the
existing precedent in this codebase. A sliding window is more accurate and
needs a sorted set per key; the accuracy is not worth it for a limit whose job
is to turn "unlimited" into "slow".

**Fails open.** Redis being down must not lock everybody out of their account.
An outage that also blocks sign-in turns a degraded service into an inaccessible
one, and the endpoint behind this is still protected by a password.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.core.logging import logger

__all__ = ["Throttle", "LOGIN", "SIGNUP", "PASSWORD_RESET", "check", "record_failure"]


@dataclass(frozen=True, slots=True)
class Throttle:
    """A named limit: ``limit`` events per ``window_seconds``."""

    name: str
    limit: int
    window_seconds: int


#: Generous enough that a person fat-fingering their password never notices,
#: tight enough that a dictionary attack is pointless. Ten failures in fifteen
#: minutes is far past what a real login looks like.
LOGIN = Throttle("login", limit=10, window_seconds=15 * 60)

#: Signup is a write and creates a tenant, a config row and a WhatsApp session
#: slot, so the cost of abuse is ours rather than a wasted guess.
SIGNUP = Throttle("signup", limit=5, window_seconds=60 * 60)

#: Each one sends an email. Unthrottled, this is a way to use us to spam a
#: third party, which is worse for our sending reputation than for us.
PASSWORD_RESET = Throttle("password_reset", limit=5, window_seconds=60 * 60)


def _hashed(value: str) -> str:
    """Identify a subject without storing it.

    Redis keys end up in logs, in ``MONITOR`` output and in anyone's shell
    history who runs ``KEYS *``. An email address is personal data and does not
    need to be there for a counter to work.
    """
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


def _key(throttle: Throttle, kind: str, subject: str) -> str:
    return f"throttle:{throttle.name}:{kind}:{_hashed(subject)}"


async def check(client, throttle: Throttle, *, ip: str | None, account: str | None) -> bool:
    """True when this attempt should be refused.

    Reads without incrementing the account counter: that one is bumped by
    :func:`record_failure` only, so a correct password never counts against the
    account and an attacker cannot lock a victim out by failing on their behalf.
    The IP counter is incremented here, since a request is a request whether or
    not it succeeds.
    """
    try:
        if ip:
            key = _key(throttle, "ip", ip)
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, throttle.window_seconds)
            if count > throttle.limit:
                logger.warning(f"throttled {throttle.name} by ip")
                return True

        if account:
            raw = await client.get(_key(throttle, "acct", account))
            if raw is not None and int(raw) > throttle.limit:
                logger.warning(f"throttled {throttle.name} by account")
                return True
    except Exception as exc:  # noqa: BLE001 - never lock everyone out
        # An outage that also blocks sign-in turns a degraded service into an
        # inaccessible one, and the endpoint is still password-protected.
        logger.warning(f"throttle check unavailable, allowing: {exc}")
        return False

    return False


async def record_failure(client, throttle: Throttle, *, account: str | None) -> None:
    """Count one failed attempt against an account."""
    if not account:
        return
    try:
        key = _key(throttle, "acct", account)
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, throttle.window_seconds)
    except Exception as exc:  # noqa: BLE001 - counting is best effort
        logger.warning(f"could not record throttle failure: {exc}")


async def clear(client, throttle: Throttle, *, account: str | None) -> None:
    """Forget an account's failures after a successful attempt.

    Otherwise a user who mistypes nine times and then succeeds stays one
    mistake away from being locked out for the rest of the window.
    """
    if not account:
        return
    try:
        await client.delete(_key(throttle, "acct", account))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"could not clear throttle counter: {exc}")


def client_ip(request) -> str | None:
    """The caller's address, as seen through the tunnel.

    ``request.client.host`` is the proxy, so it is the same for everyone and
    useless as a key. ``X-Forwarded-For`` is the real client, and the **first**
    entry is the one to take: later entries are proxies, and a caller can append
    anything they like to the header, so trusting the last is trusting the
    attacker.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return getattr(getattr(request, "client", None), "host", None)
