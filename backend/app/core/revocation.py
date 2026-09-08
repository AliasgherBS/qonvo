"""Making a token stop working before it expires (teardown X6).

The access token was a stateless JWT with a 24-hour life, no ``jti`` and no
denylist. So signing out cleared the browser's copy and left the credential
valid; removing a team member took away their membership row and left their
token working until it expired; suspending a tenant stopped nothing already in
somebody's hand; and changing a password did not end the sessions that the old
password had opened, which is the one thing people expect a password change to
do.

**Two mechanisms, because the two cases are different shapes.**

*One session.* Signing out revokes that token by its ``jti``. One key, expiring
with the token itself, so the denylist cannot grow without bound.

*Every session for somebody.* Removing a member, suspending a tenant or
changing a password has to invalidate tokens whose ``jti`` we have never seen.
A per-subject "nothing issued before this moment" timestamp does that with one
key and no enumeration: any token whose ``iat`` predates it is refused.

**Fails open, and that is a real trade rather than an oversight.** If Redis is
unreachable the check cannot be made, and refusing every request would turn a
cache outage into a total outage of a product whose database is still healthy.
So a revoked token keeps working for the remainder of its life during an
outage, and the failure is logged at error level rather than passed over. The
exposure is bounded by the token's TTL, which is the argument for shortening it
-- and shortening it without a refresh flow would sign people out mid-session,
so that is a change of its own rather than a line here.

Keys are hashed, like the throttle's: Redis keys turn up in logs, in ``MONITOR``
output and in anyone's shell history who runs ``KEYS *``, and an email address
does not need to be there for a timestamp to work.
"""

from __future__ import annotations

import datetime as dt
import hashlib

from app.core.logging import logger

__all__ = [
    "is_revoked",
    "revoke_all_for_subject",
    "revoke_all_for_tenant",
    "revoke_token",
]

_JTI = "revoked:jti:"
_SUBJECT = "revoked:sub:"
_TENANT = "revoked:tenant:"

#: How long a "revoke everything before now" marker has to outlive the tokens
#: it invalidates. Anything shorter and a token could outlive its own
#: revocation; the marker is one small key per affected subject, so generosity
#: costs nothing.
_MARKER_TTL_SECONDS = 60 * 60 * 24 * 30


def _hashed(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


def _now() -> int:
    return int(dt.datetime.now(dt.UTC).timestamp())


async def revoke_token(client, *, jti: str | None, expires_at: int | None) -> None:
    """Revoke one token, until it would have expired anyway.

    The TTL is the token's own remaining life. Keeping the entry longer would
    grow the denylist forever for no benefit: once ``exp`` has passed, the
    signature check refuses the token without help from us.
    """
    if not jti:
        # A token minted before `jti` existed, or by something that hand-rolled
        # the payload. Nothing to key on, so this cannot be honoured -- and
        # returning quietly is how a sign-out answers 204 while the token keeps
        # working, which is exactly the bug being fixed. Loud, so the next
        # divergent minter is found by reading the log rather than by testing
        # revocation by hand.
        logger.error("cannot revoke a token with no jti; it will work until it expires")
        return
    ttl = max((expires_at or 0) - _now(), 1)
    try:
        await client.set(f"{_JTI}{jti}", "1", ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"could not revoke token {jti[:8]}: {exc}")


async def revoke_all_for_subject(client, subject: str) -> None:
    """Invalidate every token already issued to this person."""
    try:
        await client.set(f"{_SUBJECT}{_hashed(subject)}", _now(), ex=_MARKER_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"could not revoke sessions for a subject: {exc}")


async def revoke_all_for_tenant(client, tenant_id) -> None:
    """Invalidate every token already issued for this tenant.

    Used when a tenant is suspended, where the point is to stop the whole
    workspace rather than one person, and where enumerating its members to
    revoke each one would race with a membership change.
    """
    try:
        await client.set(f"{_TENANT}{tenant_id}", _now(), ex=_MARKER_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"could not revoke sessions for tenant {tenant_id}: {exc}")


async def is_revoked(client, claims) -> bool:
    """True when this token must be refused despite being validly signed."""
    try:
        jti = getattr(claims, "jti", None)
        if jti and await client.get(f"{_JTI}{jti}") is not None:
            return True

        issued_at = getattr(claims, "issued_at", None)
        if issued_at is None:
            # No `iat` to compare against, so the markers cannot apply. Tokens
            # minted by this codebase always carry one.
            return False

        for key in (
            f"{_SUBJECT}{_hashed(claims.subject)}",
            *(
                [f"{_TENANT}{claims.tenant_id}"]
                if getattr(claims, "tenant_id", None) is not None
                else []
            ),
        ):
            raw = await client.get(key)
            if raw is None:
                continue
            # Redis may hand back bytes or str depending on decode_responses.
            marker = int(raw.decode() if isinstance(raw, bytes) else raw)
            # `<` rather than `<=`: a token minted in the same second as the
            # revocation is the new one somebody was just issued, and refusing
            # it would sign them out of the session they are creating.
            if issued_at < marker:
                return True
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.error(f"revocation check unavailable, allowing request: {exc}")
        return False

    return False
