"""Integration management — connect Google Calendar / Sheets (DESIGN.md §7).

Owner-facing CRUD plus a ``/test`` probe that verifies the service-account key is
valid and the target Calendar/Sheet has actually been shared with it. Secrets are
never returned; only the service-account email (to share with) and target ids.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.core.logging import logger
from app.integrations import GOOGLE_CALENDAR, SUPPORTED_PROVIDERS
from app.integrations.resolver import build_calendar_client, build_sheets_client
from app.services import integrations as svc

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class IntegrationUpdateRequest(BaseModel):
    config: dict | None = None
    # Full Google service-account key JSON. Write-only — never echoed back.
    service_account_json: str | None = None
    enabled: bool | None = None


class IntegrationResponse(BaseModel):
    provider: str
    enabled: bool
    config: dict
    has_credentials: bool
    has_tenant_key: bool
    service_account_email: str | None


class TestResult(BaseModel):
    ok: bool
    message: str
    service_account_email: str | None = None


def _require_supported(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown integration provider: {provider}",
        )


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationResponse]:
    """Every supported provider, connected or not (stub rows for the unconnected)."""
    existing = {i.provider: i for i in await svc.list_integrations(db, tenant_id)}
    out: list[IntegrationResponse] = []
    for provider in SUPPORTED_PROVIDERS:
        integration = existing.get(provider)
        if integration is not None:
            out.append(IntegrationResponse(**svc.sanitized(integration)))
        else:
            out.append(
                IntegrationResponse(
                    provider=provider,
                    enabled=False,
                    config={},
                    has_credentials=False,
                    has_tenant_key=False,
                    service_account_email=None,
                )
            )
    return out


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
            db,
            tenant_id,
            provider,
            config=body.config,
            service_account_json=body.service_account_json,
            enabled=body.enabled,
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
    """Build a live client and do a cheap read to confirm credentials + sharing."""
    _require_supported(provider)
    integration = await svc.get_integration(db, tenant_id, provider)
    email = svc.sanitized(integration)["service_account_email"] if integration else None

    builder = build_calendar_client if provider == GOOGLE_CALENDAR else build_sheets_client
    try:
        client = await builder(db, tenant_id)
    except Exception as exc:  # noqa: BLE001 — surfaced as a failed test, not a 500
        logger.bind(tenant_id=str(tenant_id)).warning(f"integration test build failed: {exc}")
        return TestResult(ok=False, message=str(exc), service_account_email=email)

    if client is None:
        target = "calendar_id" if provider == GOOGLE_CALENDAR else "spreadsheet_id"
        return TestResult(
            ok=False,
            message=f"Not configured — add a service-account key and a {target}.",
            service_account_email=email,
        )

    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        share_hint = (
            "calendar" if provider == GOOGLE_CALENDAR else "spreadsheet"
        )
        return TestResult(
            ok=False,
            message=(
                f"Couldn't reach the {share_hint}. Make sure it's shared with "
                f"{email or 'the service-account email'}. ({exc})"
            ),
            service_account_email=email,
        )

    label = "Calendar" if provider == GOOGLE_CALENDAR else "Sheet"
    return TestResult(ok=True, message=f"{label} connected.", service_account_email=email)


__all__ = ["router"]
