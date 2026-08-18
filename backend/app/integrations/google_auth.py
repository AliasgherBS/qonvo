"""Turn a Google *access token* into an API client (lazy imports).

``google-auth`` / ``google-api-python-client`` are imported *inside* functions so
the skill and test modules that only ever touch injected fakes never pay the
import cost — and unit tests run without the heavy client installed.

Refreshing is not google-auth's job here: ``app.integrations.resolver`` mints and
caches access tokens over async httpx, and hands a bare token in. The credentials
object is built without refresh material on purpose, so google-auth can never
attempt its own blocking, sync-over-``requests`` refresh from inside a thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class GoogleAuthError(Exception):
    """Raised when the Google client libraries are missing or a client won't build."""


def build_credentials(access_token: str, scopes: Sequence[str]) -> Any:
    """Wrap a bare access token as google-auth credentials.

    No ``refresh_token``/``token_uri`` is supplied. google-auth treats
    ``expiry is None`` as "not expired", so it never tries to refresh and never
    blocks — expiry is handled upstream by the token cache's early TTL.
    """
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover - dependency always present in prod
        raise GoogleAuthError("google-auth is not installed") from exc
    if not access_token:
        raise GoogleAuthError("no access token available for this integration")
    return Credentials(token=access_token, scopes=list(scopes))


def build_service(api: str, version: str, access_token: str, scopes: Sequence[str]) -> Any:
    """Build an authenticated Google API client ``service`` resource."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise GoogleAuthError("google-api-python-client is not installed") from exc
    credentials = build_credentials(access_token, scopes)
    return build(api, version, credentials=credentials, cache_discovery=False)


__all__ = ["GoogleAuthError", "build_credentials", "build_service"]
