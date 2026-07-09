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
class TokenError(Exception):
    """Raised when a JWT is missing, expired, or otherwise invalid."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    tenant_id: UUID | None
    role: str | None
    is_qonvo_admin: bool
    raw: dict


def decode_jwt(token: str) -> TokenClaims:
    """Decode and verify a JWT, extracting tenant/role claims.

    ``qonvo_admin`` is a cross-tenant superadmin flag (not a tenant role), so a
    valid admin token may carry no ``tenant_id`` until it impersonates one.
    """
    options = {"require": ["exp", "sub"]}
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


__all__ = [
    "TokenClaims",
    "TokenError",
    "compute_waha_hmac",
    "decode_jwt",
    "decrypt_secret",
    "encrypt_secret",
    "verify_waha_hmac",
]
