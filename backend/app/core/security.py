"""Security primitives: WAHA HMAC verification, JWT, and Fernet encryption.

See DESIGN.md §5.1 (HMAC), §8 (JWT auth), §3 (secrets at rest).
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


# --------------------------------------------------------------------------- #
# WAHA webhook HMAC (SHA-512 over the raw request body)
# --------------------------------------------------------------------------- #
def compute_waha_hmac(raw_body: bytes, secret: str | None = None) -> str:
    """Return the hex HMAC-SHA512 of ``raw_body`` under the shared secret."""
    key = (secret if secret is not None else settings.waha_hmac_secret).encode("utf-8")
    return hmac.new(key, raw_body, hashlib.sha512).hexdigest()


def verify_waha_hmac(
    raw_body: bytes,
    provided_signature: str | None,
    secret: str | None = None,
) -> bool:
    """Constant-time check of the ``X-Webhook-Hmac`` header against the raw body.

    Returns ``False`` for a missing or malformed signature rather than raising,
    so the caller decides the HTTP response.
    """
    if not provided_signature:
        return False
    expected = compute_waha_hmac(raw_body, secret)
    return hmac.compare_digest(expected, provided_signature.strip())


# --------------------------------------------------------------------------- #
# JWT (tenant_id + role claims, minted by the dashboard — DESIGN.md §8)
# --------------------------------------------------------------------------- #
#: The `typ` every access token carries and every other kind must not.
#: Anything signed with this secret is a credential; the claim is what says
#: which kind, so the API cannot accept a token minted for another purpose.
ACCESS_TOKEN_TYPE = "access"


class TokenError(Exception):
    """Raised when a JWT is missing, expired, or otherwise invalid."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    tenant_id: UUID | None
    role: str | None
    is_qonvo_admin: bool
    raw: dict
    #: This token's unique id, for revoking exactly this session (teardown X6).
    #: ``None`` for a token minted before the claim existed, which ages out.
    jti: str | None = None
    #: When it was issued, as a unix timestamp. Compared against the
    #: "everything before this moment is void" markers that a password change
    #: or a member removal writes.
    issued_at: int | None = None


def decode_jwt(token: str) -> TokenClaims:
    """Decode and verify a JWT, extracting tenant/role claims.

    ``qonvo_admin`` is a cross-tenant superadmin flag (not a tenant role), so a
    valid admin token may carry no ``tenant_id`` until it impersonates one.
    """
    # `typ` is required, and this is the whole of X7's fix.
    #
    # Reset tokens are signed with the same secret and algorithm as access
    # tokens, and carry both `exp` and `sub`. read_password_reset_token checks
    # typ == "pwreset" correctly; this function checked nothing. The only thing
    # stopping a reset link working as a bearer token was that require_tenant
    # found no tenant_id and answered 403 -- an accident of the payload, not a
    # decision. The day somebody adds a tenant id to that payload, to greet the
    # user by business name on the reset page say, every reset email becomes a
    # thirty-minute full-access credential sitting in a URL.
    # `aud` and `iss` are required, not merely verified-if-present: PyJWT
    # skips a claim that is absent, so without this a token minted with neither
    # would sail through the very check that was added for them (teardown X9).
    options = {
        "require": [
            "exp",
            "sub",
            "typ",
            *(["aud"] if settings.jwt_audience else []),
            *(["iss"] if settings.jwt_issuer else []),
        ]
    }
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={**options, "verify_aud": settings.jwt_audience is not None},
        )
    except jwt.PyJWTError as exc:  # expired, bad signature, missing claim, ...
        raise TokenError(str(exc)) from exc

    # Requiring the claim is not enough: it has to be the right one. A reset
    # token carries typ="pwreset" and would otherwise satisfy the requirement.
    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise TokenError(f"token type {payload.get('typ')!r} is not an access token")

    raw_tenant = payload.get("tenant_id")
    tenant_id: UUID | None = None
    if raw_tenant:
        try:
            tenant_id = UUID(str(raw_tenant))
        except ValueError as exc:
            raise TokenError("tenant_id is not a valid UUID") from exc

    return TokenClaims(
        subject=str(payload["sub"]),
        tenant_id=tenant_id,
        role=payload.get("role"),
        is_qonvo_admin=bool(payload.get("qonvo_admin", False)),
        raw=payload,
        jti=payload.get("jti"),
        issued_at=int(payload["iat"]) if payload.get("iat") is not None else None,
    )


# --------------------------------------------------------------------------- #
# Fernet encryption for per-tenant integration credentials (DESIGN.md §3)
# --------------------------------------------------------------------------- #
@lru_cache
def _fernet() -> Fernet:
    return Fernet(settings.fernet_key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a credential string, returning a URL-safe token."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenError("could not decrypt integration credential") from exc


# --------------------------------------------------------------------------- #
# Password hashing (argon2 via passlib) — Phase 1 login (DESIGN.md §8)
# --------------------------------------------------------------------------- #
from passlib.context import CryptContext  # noqa: E402

#: Argon2id parameters, pinned rather than inherited (teardown X9).
#:
#: These were passlib's defaults, which means a library upgrade could change
#: the work factor silently -- downwards as easily as upwards, and nothing in
#: the codebase would say so. Pinned, so a change to how expensive it is to
#: guess a password is a change to this file.
#:
#: The values are the ones already in effect, so pinning them changes nothing
#: except making them a decision. That matters: the first attempt at this
#: pinned OWASP's published *minimum* for Argon2id (19 MiB, t=2, p=1), which is
#: markedly weaker than what passlib was already doing, and would have quietly
#: halved the work factor for every password set from then on. A floor is not a
#: target, and checking what the library actually did before pinning it is the
#: whole job.
#:
#: 64 MiB comfortably exceeds that floor. Memory is the parameter that matters
#: against GPU cracking, which is why it is the large one.
#:
#: Changing these later is safe in both directions for *reading*: passlib
#: records the parameters in the hash, so an existing hash still verifies, and
#: ``deprecated="auto"`` marks it for rehash on the owner's next successful
#: login. It is only new hashes that get the new cost.
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 65536
ARGON2_PARALLELISM = 4

_pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",
    argon2__time_cost=ARGON2_TIME_COST,
    argon2__memory_cost=ARGON2_MEMORY_COST_KIB,
    argon2__parallelism=ARGON2_PARALLELISM,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2 for storage in ``users.hashed_password``."""
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    """Constant-time verify of a plaintext password against a stored argon2 hash.

    Returns ``False`` for a missing/blank hash rather than raising, so callers can
    treat "no password set" the same as "wrong password".
    """
    if not hashed:
        return False
    try:
        return _pwd_context.verify(password, hashed)
    except ValueError:
        return False


__all__ = [
    "TokenClaims",
    "TokenError",
    "compute_waha_hmac",
    "decode_jwt",
    "decrypt_secret",
    "encrypt_secret",
    "hash_password",
    "verify_password",
    "verify_waha_hmac",
]
