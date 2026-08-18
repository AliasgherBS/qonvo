"""Google OAuth 2.0 authorization-code flow, over plain ``httpx``.

Deliberately *not* using ``google-auth-oauthlib``: the whole dance is four
documented HTTP calls, ``httpx`` is already a dependency and is async (google-auth
refreshes sync-over-``requests``, which would block the event loop), and injecting
an ``httpx.AsyncClient`` makes every function here testable against
``httpx.MockTransport`` with no network and no monkeypatching.

Nothing in this module touches the database or Redis, and nothing here ever logs a
``code``, an access token, or a refresh token.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.logging import logger

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

CALLBACK_PATH = "/api/integrations/oauth/callback"

_TIMEOUT = httpx.Timeout(20.0)


class GoogleOAuthError(Exception):
    """Google rejected an OAuth request, or it isn't configured."""


class GoogleReauthRequired(GoogleOAuthError):
    """The stored refresh token is dead — the owner must reconnect.

    Raised on ``400 invalid_grant``, which is what Google returns once the owner
    revokes access at myaccount.google.com, changes their password, or the token
    ages out. Distinct from a transient failure because the remedy is different:
    no amount of retrying fixes it.
    """


@dataclass(frozen=True, slots=True)
class TokenBundle:
    """A token-endpoint response, normalised.

    ``granted_scopes`` is what Google actually granted, parsed from the response's
    ``scope`` string — never what we requested. Google supports partial consent,
    so the two can differ and only the granted set is safe to act on.
    """

    access_token: str
    expires_in: int
    refresh_token: str | None
    granted_scopes: tuple[str, ...]
    account_email: str | None


def is_configured() -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


def _require_configured() -> tuple[str, str]:
    if not is_configured():
        raise GoogleOAuthError(
            "Google OAuth is not configured — set QONVO_GOOGLE_OAUTH_CLIENT_ID "
            "and QONVO_GOOGLE_OAUTH_CLIENT_SECRET."
        )
    return settings.google_oauth_client_id, settings.google_oauth_client_secret  # type: ignore[return-value]


def redirect_uri() -> str:
    """The exact redirect URI registered in the Google Cloud console."""
    return f"{settings.google_oauth_redirect_base.rstrip('/')}{CALLBACK_PATH}"


def authorize_url(
    *,
    state: str,
    scopes: Sequence[str],
    login_hint: str | None = None,
) -> str:
    """Google's consent URL for one provider's scopes.

    ``prompt=consent`` is not optional here: without it a *re*-connect returns no
    refresh token at all, and we'd silently keep serving the stale one until it
    died. The cost is re-showing the consent screen on every reconnect, which is
    the right trade. ``include_granted_scopes`` is deliberately omitted — it would
    widen each grant to cover the other provider's scopes and make the
    shared-grant revocation coupling worse (see ``revoke``).
    """
    client_id, _ = _require_configured()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _decode_id_token_email(id_token: str | None) -> str | None:
    """Read ``email`` out of an id_token payload *without* verifying the signature.

    Safe precisely here and nowhere else: this token came straight back from
    Google's token endpoint over TLS in a direct server-to-server call, which is
    the documented case where verification is unnecessary. It saves pulling in a
    JWKS client for what is only a display string. A browser-supplied id_token
    (the SSO path) is attacker-controlled and MUST be verified properly instead.
    """
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        return None
    email = claims.get("email")
    return email if isinstance(email, str) else None


def _bundle(data: dict) -> TokenBundle:
    return TokenBundle(
        access_token=data.get("access_token") or "",
        # Gemini-style defensive parse: treat a missing/None expiry as "short".
        expires_in=int(data.get("expires_in") or 0),
        refresh_token=data.get("refresh_token"),
        granted_scopes=tuple((data.get("scope") or "").split()),
        account_email=_decode_id_token_email(data.get("id_token")),
    )


async def _post(
    url: str, form: dict[str, str], *, client: httpx.AsyncClient | None = None
) -> httpx.Response:
    if client is not None:
        return await client.post(url, data=form)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as owned:
        return await owned.post(url, data=form)


def _raise_for_token_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        payload = response.json()
        error = payload.get("error") or ""
        description = payload.get("error_description") or ""
    except ValueError:
        error, description = "", response.text[:200]
    detail = f"{error}: {description}".strip(": ") or f"HTTP {response.status_code}"
    if error == "invalid_grant":
        raise GoogleReauthRequired(detail)
    raise GoogleOAuthError(detail)


async def exchange_code(code: str, *, client: httpx.AsyncClient | None = None) -> TokenBundle:
    """Trade a callback ``code`` for tokens."""
    client_id, client_secret = _require_configured()
    response = await _post(
        TOKEN_ENDPOINT,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
        client=client,
    )
    _raise_for_token_error(response)
    return _bundle(response.json())


async def refresh_access_token(
    refresh_token: str, *, client: httpx.AsyncClient | None = None
) -> TokenBundle:
    """Mint a fresh access token. Raises ``GoogleReauthRequired`` if the grant died."""
    client_id, client_secret = _require_configured()
    response = await _post(
        TOKEN_ENDPOINT,
        {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        client=client,
    )
    _raise_for_token_error(response)
    # A refresh response carries no refresh_token; keep the one we already hold.
    return _bundle(response.json())


async def revoke(token: str, *, client: httpx.AsyncClient | None = None) -> bool:
    """Revoke a grant at Google. Never raises — returns success.

    Caveat that shapes the caller: this invalidates *every* token issued to this
    client id for that Google account, not just the scopes of one provider. So
    revoking on a Sheets disconnect would also kill the tenant's Calendar. Callers
    must only revoke when no other provider row still holds a refresh token.
    """
    try:
        response = await _post(REVOKE_ENDPOINT, {"token": token}, client=client)
    except httpx.HTTPError as exc:
        logger.warning(f"google oauth revoke failed to reach Google: {exc}")
        return False
    if response.status_code >= 400:
        logger.warning(f"google oauth revoke rejected: HTTP {response.status_code}")
        return False
    return True


__all__ = [
    "AUTH_ENDPOINT",
    "CALLBACK_PATH",
    "REVOKE_ENDPOINT",
    "TOKEN_ENDPOINT",
    "GoogleOAuthError",
    "GoogleReauthRequired",
    "TokenBundle",
    "authorize_url",
    "exchange_code",
    "is_configured",
    "redirect_uri",
    "refresh_access_token",
    "revoke",
]
