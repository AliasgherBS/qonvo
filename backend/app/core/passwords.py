"""What counts as an acceptable password (teardown X5).

``Field(min_length=8, max_length=128)`` was the whole policy, on signup, on
change and on reset. ``password1``, ``qonvo123`` and the business's own name all
passed. Argon2 makes each guess expensive and the throttle makes bulk guessing
slow, which is why this was medium rather than high, but neither does anything
about a password that is already sitting in a breach corpus.

Shaped to NIST 800-63B, which is what most auditors now follow, and which is
explicit about the direction: **raise the minimum length, drop composition
rules, screen against known-compromised passwords.** Complexity requirements
make passwords worse rather than better -- they push people towards
``Passw0rd!`` and away from a long phrase -- so there are deliberately no rules
here about uppercase, digits or symbols.

**The breach check fails open.** It is an outbound HTTP call to a third party
on the critical path of signing up, and refusing a registration because
someone else's service is slow trades a real customer for a hypothetical
attacker. A slow or unreachable check logs and allows.

**k-anonymity, so the password never leaves this process.** Only the first five
characters of the SHA-1 hash go to Have I Been Pwned; it answers with every
suffix in that bucket and the comparison happens here. ``Add-Padding`` is sent
so the response size does not reveal how large the bucket was.
"""

from __future__ import annotations

import hashlib
import re

import httpx

from app.core.logging import logger

__all__ = [
    "MAX_LENGTH",
    "MIN_LENGTH",
    "PasswordRejected",
    "check_password",
    "is_breached",
    "reasons_password_is_weak",
]

#: NIST's floor is 8; its recommendation for a memorised secret is longer, and
#: 12 is where a passphrase becomes plausible while a mangled word does not.
MIN_LENGTH = 12

#: Argon2 has no practical input limit, but an unbounded field is a cheap way
#: to make somebody hash a megabyte per request.
MAX_LENGTH = 128

_HIBP_RANGE = "https://api.pwnedpasswords.com/range/"

#: Long enough that a slow third party does not become our latency, short
#: enough that a signup does not feel broken.
_HIBP_TIMEOUT_SECONDS = 3.0


class PasswordRejected(ValueError):
    """The password is not acceptable. ``reasons`` is user-facing text."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(" ".join(reasons))
        self.reasons = reasons


def _tokens(value: str | None) -> set[str]:
    """Words worth refusing, from an email or a business name.

    A business called "The Clinic" should not be able to use ``theclinic`` or
    ``the-clinic``, so this splits on anything that is not a letter or digit
    and keeps the pieces long enough to matter. Two-letter fragments would
    reject half the dictionary.
    """
    if not value:
        return set()
    local = value.split("@")[0]
    return {piece for piece in re.split(r"[^a-z0-9]+", local.lower()) if len(piece) >= 4}


def reasons_password_is_weak(
    password: str, *, email: str | None = None, business_name: str | None = None
) -> list[str]:
    """Every reason to refuse this password, as sentences for the person typing.

    All of them at once rather than the first: a form that reveals one problem
    per submission is a form people fight.
    """
    reasons: list[str] = []
    stripped = password.strip()

    if len(password) < MIN_LENGTH:
        reasons.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        reasons.append(f"Use at most {MAX_LENGTH} characters.")
    if len(set(stripped)) <= 2:
        # "aaaaaaaaaaaa" and "abababababab" clear a length check and are not
        # passwords, and neither is twelve spaces -- which an earlier version
        # of this accepted, because it guarded on `stripped` being non-empty
        # and an all-whitespace password strips to nothing. Found by a test
        # written for the repetition case.
        #
        # Not a composition rule: spaces are allowed and encouraged inside a
        # passphrase. What is refused is a password made of nothing else.
        reasons.append("That is too repetitive to be a password.")

    lowered = password.lower()
    for token in _tokens(email) | _tokens(business_name):
        if token in lowered:
            reasons.append(
                "Do not use your business name or your email address in your password."
            )
            break

    return reasons


async def is_breached(password: str) -> bool:
    """Whether this password appears in Have I Been Pwned's corpus.

    Returns ``False`` when the check cannot be made. See the module docstring:
    failing closed here means a third party's outage stops registrations.
    """
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=_HIBP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{_HIBP_RANGE}{prefix}",
                headers={"Add-Padding": "true", "User-Agent": "Qonvo/1.0"},
            )
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.warning(f"breach check unavailable, allowing password: {exc}")
        return False

    for line in response.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix:
            # Padding entries are real suffixes with a count of zero.
            return count.strip() not in ("", "0")
    return False


async def check_password(
    password: str, *, email: str | None = None, business_name: str | None = None
) -> None:
    """Raise :class:`PasswordRejected` unless the password is acceptable."""
    reasons = reasons_password_is_weak(
        password, email=email, business_name=business_name
    )
    # The breach lookup is skipped when the password already fails, so a
    # hopeless one costs no outbound request.
    if not reasons and await is_breached(password):
        reasons.append(
            "That password has appeared in a known data breach. Choose a different one."
        )
    if reasons:
        raise PasswordRejected(reasons)
