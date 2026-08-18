"""Resolve per-tenant OAuth grants into live Google clients (§7).

Credential model: the owner completes a Google consent flow and Qonvo stores the
resulting refresh token Fernet-encrypted in ``integrations.encrypted_credentials``.
Non-secret metadata (granted scopes, connected account, target ids) lives in
``integrations.config`` — deliberately, so ``credential_state`` and
``ready_providers`` can answer without decrypting anything on every dashboard load.

Access tokens are minted on demand and cached in Redis; see ``token_cache`` for
why the cache can't be process-local.

``ready_providers`` gates the skill registry so a skill is only offered to the
model when its integration is genuinely usable. ``resolve_integration_client`` is
what handlers call at tool-execution time; it honours a client injected on
:class:`SkillContext` (tests / pre-resolution) before building a real one.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.core.security import TokenError, decrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from app.integrations.calendar import CalendarClient, GoogleCalendarClient
from app.integrations.google_oauth import GoogleReauthRequired, refresh_access_token
from app.integrations.scopes import SCOPES, missing_scopes
from app.integrations.sheets import GoogleSheetsClient, SheetsClient
from app.integrations.token_cache import (
    cache_access_token,
    get_cached_access_token,
    invalidate_access_token,
)
from app.models.skill import Integration

# credential_state() results.
STATE_MISSING = "missing"
STATE_REAUTH_REQUIRED = "reauth_required"
STATE_SCOPE_UPGRADE_REQUIRED = "scope_upgrade_required"
STATE_OK = "ok"


class IntegrationConfigError(Exception):
    """Raised when an integration is missing credentials or its target id."""


class ReauthRequiredError(IntegrationConfigError):
    """The tenant's Google grant is dead; only the owner reconnecting fixes it."""


@dataclass(frozen=True, slots=True)
class OAuthBundle:
    """Decrypted secret material for one integration."""

    refresh_token: str


def oauth_bundle(integration: Integration | None) -> OAuthBundle | None:
    """Decrypt the stored grant. ``None`` when absent or unusable.

    Also returns ``None`` for a legacy service-account key blob (it has no
    ``refresh_token``), which is how pre-OAuth rows are retired without a data
    migration: they simply read as "not connected" until the owner clicks Connect.
    """
    if integration is None or not integration.encrypted_credentials:
        return None
    try:
        raw = decrypt_secret(integration.encrypted_credentials)
    except (TokenError, ValueError):
        logger.warning("stored google credential could not be decrypted")
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    token = data.get("refresh_token")
    return OAuthBundle(refresh_token=token) if token else None


def credential_state(integration: Integration | None) -> str:
    """How usable this integration's credential is, without any network call."""
    if integration is None or oauth_bundle(integration) is None:
        return STATE_MISSING
    config = integration.config or {}
    if config.get("needs_reauth"):
        return STATE_REAUTH_REQUIRED
    if missing_scopes(integration.provider, config.get("granted_scopes") or []):
        return STATE_SCOPE_UPGRADE_REQUIRED
    return STATE_OK


def target_id(integration: Integration) -> str | None:
    """The configured calendar/spreadsheet this integration writes to."""
    config = integration.config or {}
    if integration.provider == GOOGLE_CALENDAR:
        return config.get("calendar_id")
    if integration.provider == GOOGLE_SHEETS:
        return config.get("spreadsheet_id")
    return None


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


async def access_token_for(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    integration: Integration,
    *,
    redis: Any | None = None,
) -> str:
    """A live Google access token: cache, else refresh and cache.

    A dead grant is converted here — once — into a persisted ``needs_reauth`` flag
    plus :class:`ReauthRequiredError`, so the very next turn's ``ready_providers``
    drops the affected skills instead of letting the model keep offering them.
    """
    from app.services import integrations as svc

    state = credential_state(integration)
    if state == STATE_MISSING:
        raise IntegrationConfigError("this integration isn't connected to Google yet")
    if state == STATE_REAUTH_REQUIRED:
        raise ReauthRequiredError("Google access was revoked — reconnect the integration")
    if state == STATE_SCOPE_UPGRADE_REQUIRED:
        raise ReauthRequiredError("Qonvo needs new Google permissions — reconnect")

    if redis is None:
        from app.core.redis import get_redis

        redis = get_redis()

    cached = await get_cached_access_token(redis, tenant_id, integration.provider)
    if cached:
        return cached

    bundle = oauth_bundle(integration)
    assert bundle is not None  # guarded by credential_state above
    try:
        tokens = await refresh_access_token(bundle.refresh_token)
    except GoogleReauthRequired as exc:
        await svc.mark_needs_reauth(db, tenant_id, integration.provider)
        await invalidate_access_token(redis, tenant_id, integration.provider)
        raise ReauthRequiredError(str(exc)) from exc

    await cache_access_token(
        redis, tenant_id, integration.provider, tokens.access_token, tokens.expires_in
    )
    return tokens.access_token


async def build_calendar_client(
    db: AsyncSession, tenant_id: uuid.UUID, *, redis: Any | None = None
) -> CalendarClient | None:
    integration = await _load_integration(db, tenant_id, GOOGLE_CALENDAR)
    if integration is None:
        return None
    calendar_id = target_id(integration)
    if not calendar_id:
        return None
    token = await access_token_for(db, tenant_id, integration, redis=redis)

    from app.integrations.google_auth import build_service

    service = build_service("calendar", "v3", token, SCOPES[GOOGLE_CALENDAR])
    return GoogleCalendarClient(
        service,
        calendar_id,
        default_timezone=(integration.config or {}).get("timezone")
        or settings.google_default_timezone,
    )


async def build_sheets_client(
    db: AsyncSession, tenant_id: uuid.UUID, *, redis: Any | None = None
) -> SheetsClient | None:
    integration = await _load_integration(db, tenant_id, GOOGLE_SHEETS)
    if integration is None:
        return None
    config = integration.config or {}
    spreadsheet_id = target_id(integration)
    if not spreadsheet_id:
        return None
    token = await access_token_for(db, tenant_id, integration, redis=redis)

    from app.integrations.google_auth import build_service

    service = build_service("sheets", "v4", token, SCOPES[GOOGLE_SHEETS])
    return GoogleSheetsClient(
        service, spreadsheet_id, sheet_range=config.get("sheet_range") or "Sheet1"
    )


async def ready_providers(db: AsyncSession, tenant_id: uuid.UUID) -> set[str]:
    """Providers that are enabled AND hold a usable grant AND have a target id."""
    rows = (
        (
            await db.execute(
                select(Integration).where(
                    # Belt and braces: RLS already scopes this in request/worker
                    # paths, but an explicit predicate keeps it correct if it is
                    # ever called from a BYPASSRLS system session or on SQLite.
                    Integration.tenant_id == tenant_id,
                    Integration.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        integration.provider
        for integration in rows
        if credential_state(integration) == STATE_OK and target_id(integration)
    }


async def _alert_owner_reauth(ctx: Any, provider: str) -> None:
    """Tell the owner their Google grant died — at most once a day per provider.

    Without the dedupe every tool call in every conversation would fire an alert,
    which is how a genuine notification becomes noise the owner learns to ignore.
    """
    from app.core.redis import get_redis
    from app.models.enums import NotificationType
    from app.services.notifications import notify

    tenant_id = ctx.tenant_id
    label = "Google Calendar" if provider == GOOGLE_CALENDAR else "Google Sheets"
    try:
        redis = get_redis()
        first = await redis.set(
            f"google:reauth_alert:{tenant_id}:{provider}", "1", nx=True, ex=86_400
        )
        if not first:
            return
        await notify(
            ctx.db,
            tenant_id=tenant_id,
            type=NotificationType.disconnect,
            title=f"{label} disconnected",
            body=(
                f"Qonvo lost access to your {label}. Reconnect it in "
                "Settings → Integrations to resume bookings."
            ),
            send_gateway=getattr(ctx, "send_gateway", None),
        )
    except Exception as exc:  # noqa: BLE001 — alerting must never break a reply
        logger.bind(tenant_id=str(tenant_id)).warning(f"reauth alert failed: {exc}")


async def resolve_integration_client(ctx: Any, provider: str) -> Any | None:
    """Client for ``provider`` — injected one first, else built from the DB.

    A dead grant returns ``None`` rather than propagating: every handler already
    has a clean "not connected yet" branch for that, whereas an exception would
    reach the pipeline's blanket handler and leak ``invalid_grant`` into the
    model's context, where it would end up paraphrased at a customer.
    """
    injected = getattr(ctx, "integration_clients", None)
    if injected and provider in injected:
        return injected[provider]
    try:
        if provider == GOOGLE_CALENDAR:
            return await build_calendar_client(ctx.db, ctx.tenant_id)
        if provider == GOOGLE_SHEETS:
            return await build_sheets_client(ctx.db, ctx.tenant_id)
    except ReauthRequiredError as exc:
        logger.bind(tenant_id=str(ctx.tenant_id)).warning(
            f"{provider} needs reconnecting: {exc}"
        )
        await _alert_owner_reauth(ctx, provider)
        return None
    return None


__all__ = [
    "STATE_MISSING",
    "STATE_OK",
    "STATE_REAUTH_REQUIRED",
    "STATE_SCOPE_UPGRADE_REQUIRED",
    "IntegrationConfigError",
    "OAuthBundle",
    "ReauthRequiredError",
    "access_token_for",
    "build_calendar_client",
    "build_sheets_client",
    "credential_state",
    "oauth_bundle",
    "ready_providers",
    "resolve_integration_client",
    "target_id",
]
