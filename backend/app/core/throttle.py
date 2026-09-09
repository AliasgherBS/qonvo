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
    #: The per-IP allowance, when it should differ from the per-account one.
    #: An address is shared and an account is not, so the two are not the same
    #: question -- see ``ip_counts_successes``.
    ip_limit: int | None = None
    #: Whether a *successful* request counts against the address.
    #:
    #: True for anything whose cost is paid per attempt however it turns out:
    #: a signup creates a tenant, a config row and a session slot; a reset
    #: sends an email. Refusing those after N attempts is the entire
    #: protection, so the counter has to see all of them.
    #:
    #: False for login, where a success is somebody doing the ordinary thing
    #: and costs us nothing. Counting successes there was a real bug: ten
    #: correct logins from one office address locked out the eleventh for
    #: fifteen minutes. Verified before the fix -- twelve valid logins in a
    #: row went 200 x10 then 429, 429, with no failure anywhere.
    ip_counts_successes: bool = True

    @property
    def effective_ip_limit(self) -> int:
        return self.limit if self.ip_limit is None else self.ip_limit


#: Generous enough that a person fat-fingering their password never notices,
#: tight enough that a dictionary attack is pointless. Ten failures in fifteen
#: minutes is far past what a real login looks like.
#:
#: The address gets its own, much larger allowance, and only failures count
#: against it. Both parts matter in this market: an owner and three staff on
#: one office connection share an address, and Pakistani mobile networks put
#: whole subscriber populations behind CGNAT -- so a per-attempt limit of ten
#: per address is a limit on a business, or on a stranger, and not on an
#: attacker.
LOGIN = Throttle(
    "login",
    limit=10,
    window_seconds=15 * 60,
    ip_limit=50,
    ip_counts_successes=False,
)

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
            if throttle.ip_counts_successes:
                count = await client.incr(key)
                if count == 1:
                    await client.expire(key, throttle.window_seconds)
            else:
                # Read only. The bump lives in record_failure, so an ordinary
                # working day never accumulates against a shared address.
                raw = await client.get(key)
                count = int(raw) if raw is not None else 0
            if count > throttle.effective_ip_limit:
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


async def record_failure(
    client, throttle: Throttle, *, account: str | None, ip: str | None = None
) -> None:
    """Count one failed attempt, against the account and against the address.

    ``ip`` is where the per-address counter is bumped for a throttle that does
    not count successes. Passing it is what makes the address limit exist at
    all for login, so it is not optional in practice -- the caller that forgets
    it gets an unlimited address.
    """
    subjects = [("acct", account)]
    if ip and not throttle.ip_counts_successes:
        subjects.append(("ip", ip))
    for kind, subject in subjects:
        if not subject:
            continue
        try:
            key = _key(throttle, kind, subject)
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


#: The header our own edge sets, and the only one here a caller cannot forge.
#:
#: Cloudflare overwrites ``CF-Connecting-IP`` on every request it proxies, so
#: whatever a client puts there is discarded. ``X-Forwarded-For`` gets no such
#: treatment: Cloudflare adds to it and leaves what was already there, which is
#: why the value below is preferred over it.
_EDGE_IP_HEADER = "cf-connecting-ip"


def client_ip(request) -> str | None:
    """The caller's address, as seen through the tunnel.

    ``request.client.host`` is the proxy, so it is the same for everyone and
    useless as a key.

    The header to believe is ``CF-Connecting-IP``. ``X-Forwarded-For`` is
    **caller-controlled** and was being trusted, which made every per-address
    limit here optional: send a different value each time and the counter never
    accumulates. Verified against production before this change -- one request
    to ``POST /api/auth/forgot-password`` carrying
    ``X-Forwarded-For: 203.0.113.250`` created its own counter and left the real
    client's sitting at 1. That is not only the login limiter; it is also the
    five-signups-per-hour cap, which is the only thing standing between a
    script and unlimited tenant rows.

    Why not simply take the *last* entry, which is the usual advice: the chain
    here is client -> Cloudflare -> cloudflared -> uvicorn, and cloudflared
    dials uvicorn over loopback. If it appends, the last entry is ``127.0.0.1``
    for every caller on earth, and a single shared counter would throttle the
    whole product at ten attempts a window. Guessing wrong in that direction is
    far worse than the bug being fixed, so the fallback below is deliberately
    left exactly as it was rather than changed on an assumption.

    NOT YET CONFIRMED ON PRODUCTION: that ``CF-Connecting-IP`` arrives at all.
    It is documented and it is what Cloudflare sets, but this codebase has been
    wrong about a forwarded header before (``AUTH_URL``, where the tunnel
    forwarded ``Host`` and Auth.js still built the wrong redirect URI). Confirm
    it the same way the bug was found, which costs one request: send a
    ``forgot-password`` through ``api.qonvo.org`` with a bogus
    ``X-Forwarded-For``, then check which ``throttle:password_reset:ip:<hash>``
    key it lands on. sha256(ip)[:32] of the real client means the header is
    being read; sha256 of the spoofed value means it is not.
    """
    edge = request.headers.get(_EDGE_IP_HEADER)
    if edge and edge.strip():
        return edge.strip()

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return getattr(getattr(request, "client", None), "host", None)
