"""Tenant configuration — persona, providers, hours, escalation (DESIGN.md §10 Settings).

``ConfigUpdateRequest``/``_config_to_dict`` are also imported by ``app.api.admin``
for the ops-console equivalent (``PUT /api/admin/tenants/{id}/config``) so both
surfaces validate and serialize identically.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.tenant import TenantConfig

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdateRequest(BaseModel):
    persona: str | None = None
    business_name: str | None = None
    primary_language: str | None = None
    tone: str | None = None
    custom_instructions: str | None = None
    business_hours: dict | None = None
    owner_alert_number: str | None = None
    escalation_rules: dict | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    payment_details: str | None = None

    @field_validator("owner_alert_number")
    @classmethod
    def _validate_owner_alert_number(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v or not v.replace("+", "").isdigit():
            raise ValueError("owner_alert_number must be digits with an optional leading +")
        return v

    @field_validator("primary_language")
    @classmethod
    def _validate_primary_language(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not v or len(v) > 16:
            raise ValueError("primary_language must be a short language code (e.g. 'en')")
        return v


class ConfigResponse(BaseModel):
    persona: str | None
    business_name: str | None
    languages: list
    primary_language: str
    tone: str | None
    custom_instructions: str | None
    business_hours: dict
    owner_alert_number: str | None
    escalation_rules: dict
    llm_provider: str | None
    llm_model: str | None
    payment_details: str | None


def _config_to_dict(row: TenantConfig) -> ConfigResponse:
    return ConfigResponse(
        persona=row.persona,
        business_name=row.business_name,
        languages=row.languages,
        primary_language=row.primary_language,
        tone=row.tone,
        custom_instructions=row.custom_instructions,
        business_hours=row.business_hours,
        owner_alert_number=row.owner_alert_number,
        escalation_rules=row.escalation_rules,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        payment_details=row.payment_details,
    )


def _apply_config_update(row: TenantConfig, body: ConfigUpdateRequest) -> None:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)


async def _get_or_create_config(db: AsyncSession, tenant_id: UUID) -> TenantConfig:
    row = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if row is None:
        row = TenantConfig(tenant_id=tenant_id)
        db.add(row)
        await db.flush()
    return row


@router.get("", response_model=ConfigResponse)
async def get_config(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    row = await _get_or_create_config(db, tenant_id)
    return _config_to_dict(row)


@router.put("", response_model=ConfigResponse)
async def update_config(
    body: ConfigUpdateRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> ConfigResponse:
    row = await _get_or_create_config(db, tenant_id)
    _apply_config_update(row, body)
    await db.flush()
    return _config_to_dict(row)


__all__ = ["ConfigUpdateRequest", "router"]
