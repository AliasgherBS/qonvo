"""Integration credential management for the owner API (DESIGN.md §7).

Stores per-tenant Google OAuth refresh tokens Fernet-encrypted and exposes only
non-secret metadata (connected account, granted scopes, target ids) back to the
dashboard.

Secret/non-secret split is deliberate: the encrypted blob holds *only* the refresh
token, while scopes and account email go in ``config``. The client id and secret
are the same for every tenant and live in settings, so duplicating them per row
would turn a client-secret rotation into a re-encrypt-every-row migration.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.security import encrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS, SUPPORTED_PROVIDERS
from app.integrations.resolver import (
    STATE_OK,
    credential_state,
    oauth_bundle,
    target_id,
)
from app.integrations.scopes import CALENDAR_PROVISIONS_OWN
from app.models.skill import Integration

# Config keys the *owner* may write via PUT (anything else is ignored).
# Target ids are absent on purpose: ``calendar_id`` is provisioned by Qonvo, and
# under per-file ``drive.file`` scope a hand-typed ``spreadsheet_id`` is
# unreachable anyway — it must arrive from the Picker via /select.
_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    GOOGLE_CALENDAR: ("timezone",) if CALENDAR_PROVISIONS_OWN else ("calendar_id", "timezone"),
    GOOGLE_SHEETS: ("sheet_range",),
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


def _merge_config(integration: Integration, updates: dict) -> None:
    """Merge into ``config``, reassigning the dict so SQLAlchemy flushes it.

    Two traps in one helper. ``JSONBType`` is plain JSONB with no ``MutableDict``,
    so in-place mutation is silently lost. And config now mixes owner-written keys
    with system-written ones (``calendar_id``, ``granted_scopes``), so a replace
    would let an owner PUT of just ``timezone`` wipe the target id and silently
    disconnect the tenant.
    """
    integration.config = {**(integration.config or {}), **updates}


def sanitized(integration: Integration) -> dict:
    """Non-secret view of an integration row for API responses.

    Never decrypts: everything here reads from ``config`` plus the presence of the
    encrypted blob, so listing integrations costs no Fernet work.
    """
    config = integration.config or {}
    state = credential_state(integration)
    return {
        "provider": integration.provider,
        "enabled": integration.enabled,
        "config": config,
        "status": state,
        "connected": state == STATE_OK and bool(target_id(integration)),
        "account_email": config.get("account_email"),
        "granted_scopes": list(config.get("granted_scopes") or []),
        "connected_at": config.get("connected_at"),
    }


def unconnected(provider: str) -> dict:
    """The stub row the API returns for a provider the tenant hasn't connected."""
    from app.integrations.resolver import STATE_MISSING

    return {
        "provider": provider,
        "enabled": False,
        "config": {},
        "status": STATE_MISSING,
        "connected": False,
        "account_email": None,
        "granted_scopes": [],
        "connected_at": None,
    }


async def list_integrations(db: AsyncSession, tenant_id: uuid.UUID) -> list[Integration]:
    return list(
        (await db.execute(select(Integration).where(Integration.tenant_id == tenant_id)))
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


async def _get_or_create(
    db: AsyncSession, tenant_id: uuid.UUID, provider: str
) -> Integration:
    integration = await get_integration(db, tenant_id, provider)
    if integration is None:
        integration = Integration(tenant_id=tenant_id, provider=provider, config={})
        db.add(integration)
    return integration


async def upsert_integration(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider: str,
    *,
    config: dict | None = None,
    enabled: bool | None = None,
) -> Integration:
    """Update the owner-writable slice of a tenant's integration."""
    _require_supported(provider)
    integration = await _get_or_create(db, tenant_id, provider)

    if config is not None:
        _merge_config(integration, _clean_config(provider, config))
    if enabled is not None:
        integration.enabled = enabled

    await db.flush()
    return integration


async def store_oauth_credentials(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider: str,
    *,
    refresh_token: str,
    granted_scopes: Sequence[str],
    account_email: str | None,
) -> Integration:
    """Persist a completed consent. Clears any prior ``needs_reauth`` flag."""
    _require_supported(provider)
    integration = await _get_or_create(db, tenant_id, provider)

    # An object rather than a bare string, so a future bring-your-own-client-id
    # can add fields without a stored-format migration.
    integration.encrypted_credentials = encrypt_secret(
        json.dumps({"refresh_token": refresh_token})
    )
    integration.enabled = True

    config = {**(integration.config or {})}
    config.pop("needs_reauth", None)
    config.pop("needs_reauth_at", None)
    config.pop("needs_provisioning", None)
    config["granted_scopes"] = list(granted_scopes)
    config["connected_at"] = dt.datetime.now(dt.UTC).isoformat()
    if account_email:
        config["account_email"] = account_email
    integration.config = config

    await db.flush()
    return integration


async def mark_needs_reauth(db: AsyncSession, tenant_id: uuid.UUID, provider: str) -> None:
    """Flag a dead grant so ``ready_providers`` stops offering its skills."""
    integration = await get_integration(db, tenant_id, provider)
    if integration is None:
        return
    _merge_config(
        integration,
        {"needs_reauth": True, "needs_reauth_at": dt.datetime.now(dt.UTC).isoformat()},
    )
    await db.flush()


async def mark_needs_provisioning(
    db: AsyncSession, tenant_id: uuid.UUID, provider: str
) -> None:
    """Record that connect succeeded but creating the target did not."""
    integration = await get_integration(db, tenant_id, provider)
    if integration is None:
        return
    _merge_config(integration, {"needs_provisioning": True})
    await db.flush()


async def set_calendar_target(
    db: AsyncSession,
    integration: Integration,
    *,
    calendar_id: str,
    summary: str,
    timezone: str,
) -> Integration:
    updates = {
        "calendar_id": calendar_id,
        "calendar_summary": summary,
        "timezone": (integration.config or {}).get("timezone") or timezone,
    }
    config = {**(integration.config or {}), **updates}
    config.pop("needs_provisioning", None)
    integration.config = config
    await db.flush()
    return integration


async def set_sheet_target(
    db: AsyncSession,
    integration: Integration,
    *,
    spreadsheet_id: str,
    title: str,
    tabs: Sequence[str],
    sheet_range: str | None = None,
) -> Integration:
    tab_list = list(tabs)
    # Default to the first real tab rather than a hardcoded "Sheet1": a sheet the
    # owner picked may well have renamed tabs, and a wrong default would only
    # surface as "Unable to parse range" at the first append.
    resolved = sheet_range or (tab_list[0] if tab_list else "Sheet1")
    config = {
        **(integration.config or {}),
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_title": title,
        "available_tabs": tab_list,
        "sheet_range": resolved,
    }
    config.pop("needs_provisioning", None)
    integration.config = config
    await db.flush()
    return integration


async def other_google_provider_has_token(
    db: AsyncSession, tenant_id: uuid.UUID, provider: str
) -> bool:
    """Whether a *different* provider row still holds a live grant for this tenant."""
    rows = (
        (
            await db.execute(
                select(Integration).where(
                    Integration.tenant_id == tenant_id, Integration.provider != provider
                )
            )
        )
        .scalars()
        .all()
    )
    return any(oauth_bundle(row) is not None for row in rows)


async def delete_integration(db: AsyncSession, tenant_id: uuid.UUID, provider: str) -> bool:
    """Disconnect: revoke at Google when safe, drop the cached token, delete the row.

    The revoke is guarded because Google's ``/revoke`` invalidates *every* token
    issued to this client id for that account — so revoking on a Sheets disconnect
    would also kill the tenant's Calendar. When a sibling integration still holds a
    grant we delete locally and leave the Google-side grant alone.

    A failed revoke still deletes the row: the owner asked Qonvo to stop acting on
    their behalf, and keeping the credential because Google was unreachable would
    be the worse failure.
    """
    from app.integrations.google_oauth import revoke
    from app.integrations.token_cache import invalidate_access_token

    integration = await get_integration(db, tenant_id, provider)
    if integration is None:
        return False

    bundle = oauth_bundle(integration)
    if bundle is not None:
        if await other_google_provider_has_token(db, tenant_id, provider):
            logger.info(
                f"skipping google revoke for {provider}: another provider shares the grant"
            )
        elif not await revoke(bundle.refresh_token):
            logger.warning(
                f"google revoke failed for tenant {tenant_id}/{provider}; "
                "deleting locally anyway"
            )

    try:
        from app.core.redis import get_redis

        await invalidate_access_token(get_redis(), tenant_id, provider)
    except Exception as exc:  # noqa: BLE001 — never block a disconnect on Redis
        logger.warning(f"could not invalidate cached access token: {exc}")

    await db.delete(integration)
    await db.flush()
    return True


__all__ = [
    "UnknownProviderError",
    "delete_integration",
    "get_integration",
    "list_integrations",
    "mark_needs_provisioning",
    "mark_needs_reauth",
    "other_google_provider_has_token",
    "sanitized",
    "set_calendar_target",
    "set_sheet_target",
    "store_oauth_credentials",
    "unconnected",
    "upsert_integration",
]
