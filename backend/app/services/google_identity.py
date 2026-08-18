"""Verify a Google ``id_token`` from the browser (Sign in with Google).

Unlike the integrations flow — where the id_token arrives server-to-server from
Google's token endpoint over TLS and its payload can be read without checking the
signature — this token is handed to us by the *client*. It is attacker-controlled
input, so it gets the full treatment: signature against Google's published JWKS,
plus ``aud`` / ``iss`` / ``exp`` validation.

Skipping any of those would turn "Sign in with Google" into "sign in as anyone":
an unverified payload is just JSON the caller wrote. In particular, checking
``aud`` against our own client id is what stops a token minted for a *different*
Google app from being replayed here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import settings

_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_VALID_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleIdentityError(Exception):
    """The id_token was missing, malformed, expired, or not issued for Qonvo."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    email: str
    email_verified: bool
    full_name: str | None
    subject: str


@lru_cache
def _jwk_client() -> PyJWKClient:
    # PyJWKClient caches fetched signing keys internally, so this is one network
    # call per key-rotation rather than one per login.
    return PyJWKClient(_JWKS_URL, cache_keys=True)


def _verify_sync(id_token: str, audience: str) -> dict[str, Any]:
    signing_key = _jwk_client().get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        options={"require": ["exp", "aud", "iss", "sub"]},
    )


async def verify_google_id_token(id_token: str) -> GoogleIdentity:
    """Validate a browser-supplied Google id_token and extract the identity."""
    if not id_token:
        raise GoogleIdentityError("no id_token supplied")
    audience = settings.google_oauth_client_id
    if not audience:
        raise GoogleIdentityError("Google sign-in is not configured on this deployment")

    try:
        # PyJWKClient's fetch is blocking; keep it off the event loop.
        claims = await asyncio.to_thread(_verify_sync, id_token, audience)
    except jwt.PyJWTError as exc:
        raise GoogleIdentityError(f"invalid Google token: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — JWKS fetch/transport failures
        raise GoogleIdentityError(f"could not verify Google token: {exc}") from exc

    if claims.get("iss") not in _VALID_ISSUERS:
        raise GoogleIdentityError(f"unexpected token issuer: {claims.get('iss')}")

    email = claims.get("email")
    if not email:
        raise GoogleIdentityError("Google token carries no email")
    # Google sets this false for unconfirmed Workspace aliases. Trusting it would
    # let someone claim an address they don't control and inherit that account.
    if not claims.get("email_verified", False):
        raise GoogleIdentityError("this Google account's email isn't verified")

    return GoogleIdentity(
        email=str(email).lower().strip(),
        email_verified=True,
        full_name=claims.get("name") or None,
        subject=str(claims.get("sub")),
    )


__all__ = ["GoogleIdentity", "GoogleIdentityError", "verify_google_id_token"]
