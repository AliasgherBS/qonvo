"""Integration credential management for the owner API (DESIGN.md §7).

Stores per-tenant Google service-account keys Fernet-encrypted and exposes only
non-secret metadata (the service-account email the owner shares their Calendar /
Sheet with, and the target ids) back to the dashboard.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import encrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS, SUPPORTED_PROVIDERS
from app.integrations.google_auth import service_account_email
from app.integrations.resolver import IntegrationConfigError, _service_account_info
from app.models.skill import Integration

# Config keys we persist per provider (anything else is ignored).
_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    GOOGLE_CALENDAR: ("calendar_id", "timezone"),
    GOOGLE_SHEETS: ("spreadsheet_id", "sheet_range"),
}


class UnknownProviderError(Exception):
    """Raised when a provider outside SUPPORTED_PROVIDERS is requested."""


def _require_supported(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise UnknownProviderError(f"unsupported integration provider: {provider}")


def _clean_config(provider: str, config: dict | None) -> dict:
    allowed = _CONFIG_KEYS.get(provider, ())
    config = config or {}
    return {k: config[k] for k in allowed if config.get(k) not in (None, "")}


def _resolved_email(integration: Integration) -> str | None:
    """The service-account email in effect (per-tenant key, else system default)."""
    try:
        info = _service_account_info(integration)
    except IntegrationConfigError:
        return None
    return service_account_email(info) if info else None


def sanitized(integration: Integration) -> dict:
    """Non-secret view of an integration row for API responses."""
    has_tenant_key = bool(integration.encrypted_credentials)
    return {
        "provider": integration.provider,
        "enabled": integration.enabled,
        "config": integration.config or {},
        "has_credentials": has_tenant_key or bool(settings.google_service_account_json),
        "has_tenant_key": has_tenant_key,
        "service_account_email": _resolved_email(integration),
    }


async def list_integrations(db: AsyncSession, tenant_id: uuid.UUID) -> list[Integration]:
    return list(
        (
            await db.execute(
                select(Integration).where(Integration.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )


async def get_integration(
    db: AsyncSession, tenant_id: uuid.UUID, provider: str
) -> Integration | None:
    return (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id, Integration.provider == provider
            )
        )
    ).scalar_one_or_none()


def validate_service_account_json(raw: str) -> None:
    """Reject a key that isn't a parseable service-account JSON before storing it."""
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"service-account key is not valid JSON: {exc}") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError("key must be a Google service-account JSON (type: service_account)")
    if not info.get("client_email") or not info.get("private_key"):
        raise ValueError("service-account key is missing client_email/private_key")


async def upsert_integration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider: str,
    *,
    config: dict | None = None,
    service_account_json: str | None = None,
    enabled: bool | None = None,
) -> Integration:
    """Create or update a tenant's integration; encrypt a supplied key at rest."""
    _require_supported(provider)
    integration = await get_integration(db, tenant_id, provider)
    if integration is None:
        integration = Integration(tenant_id=tenant_id, provider=provider, config={})
        db.add(integration)

    if config is not None:
        integration.config = _clean_config(provider, config)
    if service_account_json is not None and service_account_json.strip():
        validate_service_account_json(service_account_json)
        integration.encrypted_credentials = encrypt_secret(service_account_json.strip())
    if enabled is not None:
        integration.enabled = enabled

    await db.flush()
    return integration


async def delete_integration(db: AsyncSession, tenant_id: uuid.UUID, provider: str) -> bool:
    integration = await get_integration(db, tenant_id, provider)
    if integration is None:
        return False
    await db.delete(integration)
    await db.flush()
    return True


__all__ = [
    "UnknownProviderError",
    "delete_integration",
    "get_integration",
    "list_integrations",
    "sanitized",
    "upsert_integration",
    "validate_service_account_json",
]
