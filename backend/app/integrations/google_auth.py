"""Google service-account credential helpers (lazy imports).

``google-auth`` / ``google-api-python-client`` are imported *inside* functions so
the skill and test modules that only ever touch injected fakes never pay the
import cost — and unit tests run without the heavy client installed.
"""

from __future__ import annotations

from typing import Any

from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS

# Minimal scopes: create/read events, and read/append sheet values.
SCOPES: dict[str, list[str]] = {
    GOOGLE_CALENDAR: ["https://www.googleapis.com/auth/calendar.events"],
    GOOGLE_SHEETS: ["https://www.googleapis.com/auth/spreadsheets"],
}


class GoogleAuthError(Exception):
    """Raised when a service-account key is malformed or credentials fail to build."""


def service_account_email(info: dict[str, Any]) -> str | None:
    """The ``client_email`` a tenant must share their Calendar/Sheet with."""
    return info.get("client_email")


def build_credentials(info: dict[str, Any], scopes: list[str]) -> Any:
    """Build scoped service-account credentials from a parsed key dict."""
    try:
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - dependency always present in prod
        raise GoogleAuthError("google-auth is not installed") from exc
    try:
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)
    except (ValueError, KeyError) as exc:
        raise GoogleAuthError(f"invalid service-account key: {exc}") from exc


def build_service(api: str, version: str, info: dict[str, Any], scopes: list[str]) -> Any:
    """Build an authenticated Google API client ``service`` resource."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise GoogleAuthError("google-api-python-client is not installed") from exc
    credentials = build_credentials(info, scopes)
    return build(api, version, credentials=credentials, cache_discovery=False)


__all__ = [
    "SCOPES",
    "GoogleAuthError",
    "build_credentials",
    "build_service",
    "service_account_email",
]
