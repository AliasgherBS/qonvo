"""Refusing signups that are not going to become customers (teardown X9).

There was no bot or abuse protection on signup beyond the rate limit, and five
tenants an hour per IP is a lot of trial tenants over a week. Each one
provisions a tenant, a config row and a WhatsApp session slot, and each one
carries a trial message quota that costs us real LLM credit if it is used.

**A blocklist, not an allowlist, and a short one.** The exhaustive
disposable-domain lists run to tens of thousands of entries, go stale weekly,
and reject real customers -- some businesses genuinely use a forwarding
service. This covers the handful that account for most throwaway signups and
nothing else. It is a speed bump, and it is honest about that: anybody
determined can register a domain for a dollar.

Email verification is the real control here, and it now exists (X2): an
unconfirmed tenant cannot connect a WhatsApp number, so a throwaway signup is
inert whatever address it used.
"""

from __future__ import annotations

__all__ = ["DISPOSABLE_DOMAINS", "is_disposable_email"]

#: The common throwaway providers, and their better-known aliases.
#:
#: Deliberately not generated from a public list at runtime: a signup path that
#: depends on fetching a file from somebody else either fails open, in which
#: case it does nothing, or fails closed, in which case a third party's outage
#: stops registrations.
DISPOSABLE_DOMAINS = frozenset(
    {
        "0-mail.com",
        "10minutemail.com",
        "20minutemail.com",
        "33mail.com",
        "discard.email",
        "dispostable.com",
        "fakeinbox.com",
        "getairmail.com",
        "getnada.com",
        "guerrillamail.com",
        "guerrillamail.info",
        "guerrillamail.net",
        "guerrillamail.org",
        "harakirimail.com",
        "inboxbear.com",
        "mailinator.com",
        "mailinator.net",
        "maildrop.cc",
        "mailnesia.com",
        "mintemail.com",
        "mohmal.com",
        "moakt.com",
        "mytemp.email",
        "sharklasers.com",
        "spam4.me",
        "temp-mail.org",
        "tempmail.com",
        "tempmail.net",
        "tempmailo.com",
        "tempr.email",
        "throwawaymail.com",
        "trashmail.com",
        "trashmail.de",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
    }
)


def is_disposable_email(email: str | None) -> bool:
    """Whether this address belongs to a known throwaway provider.

    Matches the domain and any parent of it, so ``foo.mailinator.com`` is
    caught by the ``mailinator.com`` entry -- those providers hand out
    unlimited subdomains, and listing them individually is not possible.
    """
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower().rstrip(".")
    if not domain:
        return False
    parts = domain.split(".")
    return any(
        ".".join(parts[i:]) in DISPOSABLE_DOMAINS for i in range(len(parts) - 1)
    )
