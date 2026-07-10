"""Resolve per-tenant integration credentials into live Google clients (§7).

Credential precedence: a per-tenant Fernet-encrypted service-account key wins;
otherwise the system-default key in settings is used (dev convenience — one key
covers every tenant that has shared their Calendar/Sheet with its email).

``ready_providers`` gates the skill registry so a skill is only offered to the
model when its integration is genuinely usable (enabled + creds + target id).
``resolve_integration_client`` is what handlers call at tool-execution time;
it honours a client injected on :class:`SkillContext` (tests / pre-resolution)
before building a real one from the database.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from app.integrations.calendar import CalendarClient, GoogleCalendarClient
from app.integrations.sheets import GoogleSheetsClient, SheetsClient
from app.models.skill import Integration


class IntegrationConfigError(Exception):
    """Raised when an integration is missing credentials or its target id."""


def _service_account_info(integration: Integration | None) -> dict[str, Any] | None:
    """Parsed service-account key: per-tenant override, else system default."""
    raw: str | None = None
    if integration is not None and integration.encrypted_credentials:
        raw = decrypt_secret(integration.encrypted_credentials)
    elif settings.google_service_account_json:
        raw = settings.google_service_account_json
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntegrationConfigError(f"service-account key is not valid JSON: {exc}") from exc


async def _load_integration(
    db: AsyncSession, tenant_id: uuid.UUID, provider: str
) -> Integration | None:
    return (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.provider == provider,
                Integration.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()


async def build_calendar_client(
    db: AsyncSession, tenant_id: uuid.UUID
) -> CalendarClient | None:
    integration = await _load_integration(db, tenant_id, GOOGLE_CALENDAR)
    if integration is None:
        return None
    info = _service_account_info(integration)
    calendar_id = (integration.config or {}).get("calendar_id")
    if not info or not calendar_id:
        return None
    from app.integrations.google_auth import SCOPES, build_service

    service = build_service("calendar", "v3", info, SCOPES[GOOGLE_CALENDAR])
    return GoogleCalendarClient(
        service,
        calendar_id,
        default_timezone=(integration.config or {}).get("timezone")
        or settings.google_default_timezone,
    )


async def build_sheets_client(db: AsyncSession, tenant_id: uuid.UUID) -> SheetsClient | None:
    integration = await _load_integration(db, tenant_id, GOOGLE_SHEETS)
    if integration is None:
        return None
    info = _service_account_info(integration)
    config = integration.config or {}
    spreadsheet_id = config.get("spreadsheet_id")
    if not info or not spreadsheet_id:
        return None
    from app.integrations.google_auth import SCOPES, build_service

    service = build_service("sheets", "v4", info, SCOPES[GOOGLE_SHEETS])
    return GoogleSheetsClient(
        service, spreadsheet_id, sheet_range=config.get("sheet_range") or "Sheet1"
    )


def _has_credentials(integration: Integration) -> bool:
    return bool(integration.encrypted_credentials) or bool(settings.google_service_account_json)


async def ready_providers(db: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    """Providers that are enabled AND have credentials AND a target id configured."""
    rows = (
        (await db.execute(select(Integration).where(Integration.enabled.is_(True))))
        .scalars()
        .all()
    )
    ready: set[str] = set()
    for integration in rows:
        if not _has_credentials(integration):
            continue
        config = integration.config or {}
        if integration.provider == GOOGLE_CALENDAR and config.get("calendar_id"):
            ready.add(GOOGLE_CALENDAR)
        elif integration.provider == GOOGLE_SHEETS and config.get("spreadsheet_id"):
            ready.add(GOOGLE_SHEETS)
    return ready


async def resolve_integration_client(ctx: Any, provider: str) -> Any | None:
    """Client for ``provider`` — injected one first, else built from the DB."""
    injected = getattr(ctx, "integration_clients", None)
    if injected and provider in injected:
        return injected[provider]
    if provider == GOOGLE_CALENDAR:
        return await build_calendar_client(ctx.db, ctx.tenant_id)
    if provider == GOOGLE_SHEETS:
        return await build_sheets_client(ctx.db, ctx.tenant_id)
    return None


__all__ = [
    "IntegrationConfigError",
    "build_calendar_client",
    "build_sheets_client",
    "ready_providers",
    "resolve_integration_client",
]
