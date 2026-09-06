"""Tenant configuration — persona, providers, hours, escalation (DESIGN.md §10 Settings).

``ConfigUpdateRequest``/``_config_to_dict`` are also imported by ``app.api.admin``
for the ops-console equivalent (``PUT /api/admin/tenants/{id}/config``) so both
surfaces validate and serialize identically.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.tenant import Tenant, TenantConfig

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
    voice_reply_mode: str | None = None  # "match" | "always" | "never"
    # "match" or a language code (see app/agent/language.py). Script-aware:
    # Urdu script and Roman Urdu are separate choices, because a model told
    # "reply in Urdu" always picks the Arabic script.
    reply_language_mode: str | None = None
    # Owner notification preference: alert the owner when the bot hands a
    # conversation off to a human. Stored in escalation_rules (no column).
    notify_on_handoff: bool | None = None

    @field_validator("voice_reply_mode")
    @classmethod
    def _validate_voice_reply_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"match", "always", "never"}:
            raise ValueError("voice_reply_mode must be match, always, or never")
        return v

    @field_validator("reply_language_mode")
    @classmethod
    def _validate_reply_language_mode(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.agent.language import SUPPORTED_REPLY_LANGUAGES, is_supported

        if not is_supported(v):
            allowed = ", ".join(lang.code for lang in SUPPORTED_REPLY_LANGUAGES)
            raise ValueError(f"reply_language_mode must be one of: {allowed}")
        return v

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
    voice_reply_mode: str
    reply_language_mode: str
    notify_on_handoff: bool


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
        voice_reply_mode=((row.providers or {}).get("voice") or {}).get("mode") or "match",
        reply_language_mode=(
            ((row.providers or {}).get("language") or {}).get("mode") or "match"
        ),
        # Default on: the owner is alerted on handoff unless they opt out.
        notify_on_handoff=(row.escalation_rules or {}).get("notify_on_handoff", True),
    )


def _apply_config_update(row: TenantConfig, body: ConfigUpdateRequest) -> None:
    data = body.model_dump(exclude_unset=True)
    # These two aren't columns — they live in JSON maps. Pop before the column loop.
    voice_mode = data.pop("voice_reply_mode", None)
    language_mode = data.pop("reply_language_mode", None)
    notify_on_handoff = data.pop("notify_on_handoff", None)
    for field, value in data.items():
        setattr(row, field, value)
    if voice_mode is not None:
        providers = dict(row.providers or {})
        providers["voice"] = {**(providers.get("voice") or {}), "mode": voice_mode}
        row.providers = providers  # reassign so SQLAlchemy flags the JSONB change
    if language_mode is not None:
        providers = dict(row.providers or {})
        providers["language"] = {**(providers.get("language") or {}), "mode": language_mode}
        row.providers = providers
    if notify_on_handoff is not None:
        # Merge into escalation_rules AFTER the column loop, so an escalation_rules
        # value in the same request doesn't clobber this key. Reassign for JSONB.
        rules = dict(row.escalation_rules or {})
        rules["notify_on_handoff"] = notify_on_handoff
        row.escalation_rules = rules


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
    # Keep the tenant's display name in sync with the business name edited here —
    # the topbar/JWT read Tenant.name, so otherwise the two silently diverge.
    if "business_name" in body.model_dump(exclude_unset=True) and body.business_name:
        await db.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(name=body.business_name.strip())
        )
    await db.flush()
    return _config_to_dict(row)


__all__ = ["ConfigUpdateRequest", "router"]
