"""Integration management — connect Google Calendar / Sheets (DESIGN.md §7).

The owner-facing flow is: ``POST /{provider}/oauth/start`` → Google consent →
``GET /oauth/callback``. Connect provisions the target itself (a "Qonvo Bookings"
calendar) or takes it from the Google Picker (``/google_sheets/select``), so the
owner never copies an id or shares a resource by hand.

Secrets are never returned; responses carry only the connected account, the
granted scopes, and the target metadata.
"""

from __future__ import annotations

from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_dep, require_tenant
from app.core.config import settings
from app.core.logging import logger
from app.core.tenancy import tenant_session
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS, SUPPORTED_PROVIDERS
from app.integrations.google_oauth import (
    GoogleOAuthError,
    authorize_url,
    exchange_code,
    is_configured,
)
from app.integrations.oauth_state import consume_state, issue_state
from app.integrations.provisioning import (
    ProvisioningError,
    create_spreadsheet,
    describe_spreadsheet,
    ensure_qonvo_calendar,
)
from app.integrations.resolver import (
    STATE_MISSING,
    STATE_REAUTH_REQUIRED,
    STATE_SCOPE_UPGRADE_REQUIRED,
    IntegrationConfigError,
    ReauthRequiredError,
    access_token_for,
    build_calendar_client,
    build_sheets_client,
    credential_state,
)
from app.integrations.scopes import (
    CALENDAR_PROVISIONS_OWN,
    QONVO_CALENDAR_SUMMARY,
    missing_scopes,
    scopes_for,
)
from app.integrations.token_cache import cache_access_token
from app.services import integrations as svc

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class IntegrationUpdateRequest(BaseModel):
    config: dict | None = None
    enabled: bool | None = None


class IntegrationResponse(BaseModel):
    provider: str
    enabled: bool
    config: dict
    # "missing" | "reauth_required" | "scope_upgrade_required" | "ok"
    status: str
    connected: bool
    account_email: str | None
    granted_scopes: list[str]
    connected_at: str | None


class TestResult(BaseModel):
    ok: bool
    message: str
    account_email: str | None = None


class OAuthStartResponse(BaseModel):
    authorize_url: str


class SheetSelectRequest(BaseModel):
    spreadsheet_id: str = Field(min_length=1, max_length=200)
    sheet_range: str | None = None


class SheetCreateRequest(BaseModel):
    title: str = Field(default="Qonvo Leads", min_length=1, max_length=200)


class SheetTargetResponse(BaseModel):
    spreadsheet_id: str
    title: str
    tabs: list[str]
    sheet_range: str


class PickerTokenResponse(BaseModel):
    access_token: str
    api_key: str
    app_id: str


def _require_supported(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown integration provider: {provider}",
        )


def _dashboard_redirect(**params: str) -> RedirectResponse:
    base = settings.dashboard_base_url.rstrip("/")
    return RedirectResponse(f"{base}/integrations?{urlencode(params)}", status_code=302)


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationResponse]:
    """Every supported provider, connected or not (stub rows for the unconnected)."""
    existing = {i.provider: i for i in await svc.list_integrations(db, tenant_id)}
    return [
        IntegrationResponse(
            **(
                svc.sanitized(existing[provider])
                if provider in existing
                else svc.unconnected(provider)
            )
        )
        for provider in SUPPORTED_PROVIDERS
    ]


@router.post("/{provider}/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    provider: str,
    tenant_id: UUID = Depends(require_tenant),
    redis=Depends(get_redis_dep),
) -> OAuthStartResponse:
    """Mint a single-use state and hand back Google's consent URL.

    Returns JSON rather than a 302 on purpose: a top-level browser navigation
    carries no ``Authorization`` header, and the dashboard holds the JWT in JS. The
    caller does ``window.location.assign(authorize_url)``.
    """
    _require_supported(provider)
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in isn't configured on this deployment yet.",
        )
    state = await issue_state(redis, tenant_id=tenant_id, provider=provider)
    return OAuthStartResponse(
        authorize_url=authorize_url(state=state, scopes=scopes_for(provider))
    )


async def _persist_connection(state, bundle) -> None:
    """Store a completed grant and provision the target. Own DB session.

    Uses ``tenant_session`` rather than the BYPASSRLS ``system_session``: the state
    token was minted inside an authenticated ``require_tenant`` request and is
    single-use, so the tenant is already established and there is no cross-tenant
    read to do. Handing an unauthenticated, internet-reachable endpoint a
    BYPASSRLS connection would buy nothing and would discard RLS as an independent
    check that the write lands on the tenant named in the state. (Contrast the WAHA
    webhook, which *must* use the system session because it resolves a tenant from
    a session name it cannot attribute beforehand.)
    """
    async with tenant_session(state.tenant_id) as db:
        integration = await svc.store_oauth_credentials(
            db,
            state.tenant_id,
            state.provider,
            refresh_token=bundle.refresh_token,
            granted_scopes=bundle.granted_scopes,
            account_email=bundle.account_email,
        )
        if state.provider == GOOGLE_CALENDAR and CALENDAR_PROVISIONS_OWN:
            try:
                calendar_id, created = await ensure_qonvo_calendar(
                    bundle.access_token,
                    existing_calendar_id=(integration.config or {}).get("calendar_id"),
                    timezone=(integration.config or {}).get("timezone")
                    or settings.google_default_timezone,
                )
                await svc.set_calendar_target(
                    db,
                    integration,
                    calendar_id=calendar_id,
                    summary=QONVO_CALENDAR_SUMMARY,
                    timezone=settings.google_default_timezone,
                )
                logger.bind(tenant_id=str(state.tenant_id)).info(
                    f"calendar target {'created' if created else 'reused'}: {calendar_id}"
                )
            except ProvisioningError as exc:
                # Keep the refresh token: a transient Google 5xx must not force the
                # owner back through consent. /provision retries just this step.
                logger.bind(tenant_id=str(state.tenant_id)).warning(
                    f"calendar provisioning failed, token kept: {exc}"
                )
                await svc.mark_needs_provisioning(db, state.tenant_id, state.provider)


@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    redis=Depends(get_redis_dep),
) -> RedirectResponse:
    """Google's redirect target. Always redirects; never 500s; never logs secrets.

    Deliberately has no auth dependency and no ``get_db``: it arrives as a plain
    browser navigation with only ``code`` and ``state``.
    """
    if error:
        return _dashboard_redirect(integration_error=error)

    resolved = await consume_state(redis, state or "")
    if resolved is None:
        # Unknown, expired, or replayed — the DB is never touched in this branch.
        return _dashboard_redirect(integration_error="state_expired")

    if not code:
        return _dashboard_redirect(integration_error="missing_code")

    try:
        bundle = await exchange_code(code)
    except GoogleOAuthError as exc:
        logger.warning(f"oauth code exchange failed for {resolved.provider}: {exc}")
        return _dashboard_redirect(integration_error="exchange_failed")

    if not bundle.refresh_token:
        return _dashboard_redirect(integration_error="no_refresh_token")
    if missing_scopes(resolved.provider, bundle.granted_scopes):
        return _dashboard_redirect(integration_error="partial_consent")

    try:
        await _persist_connection(resolved, bundle)
    except Exception as exc:  # noqa: BLE001 — a broken redirect is worse than a message
        logger.bind(tenant_id=str(resolved.tenant_id)).error(
            f"storing google grant failed: {exc}"
        )
        return _dashboard_redirect(integration_error="store_failed")

    try:
        await cache_access_token(
            redis,
            resolved.tenant_id,
            resolved.provider,
            bundle.access_token,
            bundle.expires_in,
        )
    except Exception as exc:  # noqa: BLE001 — cache is an optimisation
        logger.warning(f"could not cache initial access token: {exc}")

    return _dashboard_redirect(connected=resolved.provider)


@router.post("/google_calendar/provision", response_model=IntegrationResponse)
async def provision_calendar(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_dep),
) -> IntegrationResponse:
    """Retry creating the bookings calendar when the callback's attempt failed."""
    integration = await svc.get_integration(db, tenant_id, GOOGLE_CALENDAR)
    if integration is None or credential_state(integration) == STATE_MISSING:
        raise HTTPException(status_code=400, detail="Connect Google Calendar first.")
    try:
        token = await access_token_for(db, tenant_id, integration, redis=redis)
        calendar_id, _ = await ensure_qonvo_calendar(
            token,
            existing_calendar_id=(integration.config or {}).get("calendar_id"),
            timezone=(integration.config or {}).get("timezone")
            or settings.google_default_timezone,
        )
    except (IntegrationConfigError, ProvisioningError, GoogleOAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await svc.set_calendar_target(
        db,
        integration,
        calendar_id=calendar_id,
        summary=QONVO_CALENDAR_SUMMARY,
        timezone=settings.google_default_timezone,
    )
    return IntegrationResponse(**svc.sanitized(integration))


@router.get("/google_sheets/picker-token", response_model=PickerTokenResponse)
async def picker_token(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_dep),
) -> PickerTokenResponse:
    """Short-lived access token + Picker config for the browser-side chooser."""
    if not settings.google_picker_api_key or not settings.google_picker_app_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The sheet chooser isn't configured on this deployment.",
        )
    integration = await svc.get_integration(db, tenant_id, GOOGLE_SHEETS)
    if integration is None:
        raise HTTPException(status_code=400, detail="Connect Google Sheets first.")
    try:
        token = await access_token_for(db, tenant_id, integration, redis=redis)
    except IntegrationConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PickerTokenResponse(
        access_token=token,
        api_key=settings.google_picker_api_key,
        app_id=settings.google_picker_app_id,
    )


@router.post("/google_sheets/select", response_model=SheetTargetResponse)
async def select_spreadsheet(
    body: SheetSelectRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_dep),
) -> SheetTargetResponse:
    """Record the spreadsheet the owner picked, and read back its tabs.

    Under per-file ``drive.file`` scope, ``describe_spreadsheet`` succeeding *is*
    the access check — it only works for a file selected through the Picker with
    this client id, which is why there's no hand-typed-id path.
    """
    integration = await svc.get_integration(db, tenant_id, GOOGLE_SHEETS)
    if integration is None:
        raise HTTPException(status_code=400, detail="Connect Google Sheets first.")
    try:
        token = await access_token_for(db, tenant_id, integration, redis=redis)
        title, tabs = await describe_spreadsheet(token, body.spreadsheet_id)
    except (IntegrationConfigError, ProvisioningError, GoogleOAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.sheet_range and tabs and body.sheet_range not in tabs:
        raise HTTPException(
            status_code=400,
            detail=f"'{body.sheet_range}' isn't a tab in that sheet. Tabs: {', '.join(tabs)}",
        )

    await svc.set_sheet_target(
        db,
        integration,
        spreadsheet_id=body.spreadsheet_id,
        title=title,
        tabs=tabs,
        sheet_range=body.sheet_range,
    )
    config = integration.config or {}
    return SheetTargetResponse(
        spreadsheet_id=body.spreadsheet_id,
        title=title,
        tabs=tabs,
        sheet_range=config.get("sheet_range") or "Sheet1",
    )


@router.post("/google_sheets/create", response_model=SheetTargetResponse)
async def create_sheet(
    body: SheetCreateRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis_dep),
) -> SheetTargetResponse:
    """Make a fresh spreadsheet for an owner who doesn't have one yet."""
    integration = await svc.get_integration(db, tenant_id, GOOGLE_SHEETS)
    if integration is None:
        raise HTTPException(status_code=400, detail="Connect Google Sheets first.")
    try:
        token = await access_token_for(db, tenant_id, integration, redis=redis)
        spreadsheet_id, title, tabs = await create_spreadsheet(token, body.title)
    except (IntegrationConfigError, ProvisioningError, GoogleOAuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await svc.set_sheet_target(
        db, integration, spreadsheet_id=spreadsheet_id, title=title, tabs=tabs
    )
    config = integration.config or {}
    return SheetTargetResponse(
        spreadsheet_id=spreadsheet_id,
        title=title,
        tabs=tabs,
        sheet_range=config.get("sheet_range") or "Sheet1",
    )


@router.put("/{provider}", response_model=IntegrationResponse)
async def upsert_integration(
    provider: str,
    body: IntegrationUpdateRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> IntegrationResponse:
    _require_supported(provider)
    try:
        integration = await svc.upsert_integration(
            db, tenant_id, provider, config=body.config, enabled=body.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return IntegrationResponse(**svc.sanitized(integration))


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    provider: str,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    _require_supported(provider)
    await svc.delete_integration(db, tenant_id, provider)


@router.post("/{provider}/test", response_model=TestResult)
async def test_integration(
    provider: str,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> TestResult:
    """Build a live client and do a cheap read to confirm the grant still works."""
    _require_supported(provider)
    integration = await svc.get_integration(db, tenant_id, provider)
    email = (integration.config or {}).get("account_email") if integration else None
    state = credential_state(integration)

    if state == STATE_MISSING:
        return TestResult(
            ok=False, message="Not connected — click Connect Google.", account_email=email
        )
    if state == STATE_REAUTH_REQUIRED:
        return TestResult(
            ok=False,
            message="Google access was revoked. Click Reconnect to restore it.",
            account_email=email,
        )
    if state == STATE_SCOPE_UPGRADE_REQUIRED:
        return TestResult(
            ok=False,
            message="Qonvo needs new Google permissions. Click Reconnect.",
            account_email=email,
        )

    builder = build_calendar_client if provider == GOOGLE_CALENDAR else build_sheets_client
    try:
        client = await builder(db, tenant_id)
    except ReauthRequiredError:
        return TestResult(
            ok=False,
            message="Google access was revoked. Click Reconnect to restore it.",
            account_email=email,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as a failed test, not a 500
        logger.bind(tenant_id=str(tenant_id)).warning(f"integration test build failed: {exc}")
        return TestResult(ok=False, message=str(exc), account_email=email)

    if client is None:
        missing = (
            "the bookings calendar hasn't been created yet"
            if provider == GOOGLE_CALENDAR
            else "no spreadsheet has been chosen yet"
        )
        return TestResult(ok=False, message=f"Almost there — {missing}.", account_email=email)

    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        return TestResult(ok=False, message=str(exc), account_email=email)

    label = "Calendar" if provider == GOOGLE_CALENDAR else "Sheet"
    return TestResult(ok=True, message=f"{label} connected.", account_email=email)


__all__ = ["router"]
