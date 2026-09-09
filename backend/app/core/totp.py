"""Time-based one-time passwords, RFC 6238 (teardown X4).

The admin account had one password guarding a page reachable from the public
internet that can mint an owner-scoped token for any tenant on the platform.
One phished password is every customer's WhatsApp inbox, and the same account
can delete any tenant outright.

**Hand-rolled rather than a dependency**, following the same call already made
for the Prometheus endpoint. The algorithm is a counter, an HMAC and a
truncation -- about thirty lines of standard library -- and it is one of the
few pieces of cryptography where "write it yourself" is defensible, because the
specification publishes test vectors. Those vectors are the tests: if this
implementation is wrong, it disagrees with the RFC's own numbers rather than
merely with an authenticator app somebody has to hold.

The parameters are not configurable. SHA-1, six digits and a thirty-second step
are what every authenticator app assumes, and a server that chooses differently
produces codes the user's app cannot generate. SHA-1 here is not a weakness:
HMAC-SHA1 is unbroken, and the output is truncated to six digits anyway.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

__all__ = [
    "DIGITS",
    "STEP_SECONDS",
    "generate_secret",
    "provisioning_uri",
    "totp_at",
    "verify_code",
]

#: What every authenticator app assumes. Not settings.
DIGITS = 6
STEP_SECONDS = 30

#: How many steps either side of now to accept.
#:
#: One, which is thirty seconds of tolerance in each direction. Phone clocks
#: drift and people finish typing after the code rolls over; zero tolerance
#: produces "the code is wrong" for a code that was right when it was read.
#: More than one starts widening the guessing window for no usability gain.
DEFAULT_WINDOW = 1

#: 160 bits, which is what RFC 4226 requires and what the HMAC-SHA1 block
#: takes without padding or hashing.
_SECRET_BYTES = 20


def generate_secret() -> str:
    """A fresh base32 secret, in the shape authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(_SECRET_BYTES)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    # Apps display secrets without padding and users retype them with spaces
    # and in lower case. Normalising here means a hand-entered secret works.
    cleaned = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding, casefold=True)


def totp_at(secret: str, *, timestamp: int, digits: int = DIGITS, step: int = STEP_SECONDS) -> str:
    """The code for one moment. ``digits`` is a parameter only so the RFC's
    eight-digit test vectors can be checked against this function."""
    counter = timestamp // step
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    # Dynamic truncation, RFC 4226 §5.3: the low nibble of the last byte picks
    # the offset, and the high bit of the selected word is masked off so the
    # result is the same on platforms that differ about signedness.
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def verify_code(
    secret: str,
    code: str | None,
    *,
    at: int | None = None,
    window: int = DEFAULT_WINDOW,
) -> bool:
    """Whether ``code`` is valid for ``secret`` right now.

    Compared with :func:`hmac.compare_digest` rather than ``==``. A one-time
    code is short enough that a timing difference is a poor oracle, but the
    comparison is free and the habit is the point.
    """
    if not secret or not code:
        return False
    cleaned = "".join(ch for ch in code if ch.isdigit())
    if len(cleaned) != DIGITS:
        return False
    now = int(time.time()) if at is None else at
    return any(
        hmac.compare_digest(totp_at(secret, timestamp=now + offset * STEP_SECONDS), cleaned)
        for offset in range(-window, window + 1)
    )


def provisioning_uri(secret: str, *, account: str, issuer: str = "Qonvo") -> str:
    """The ``otpauth://`` URI an authenticator app scans.

    Both label and issuer are percent-encoded: the label is
    ``issuer:account``, and an unescaped colon or space in either produces a
    URI that some apps parse into the wrong account name and others reject.
    """
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )
