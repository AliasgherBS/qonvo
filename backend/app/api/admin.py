"""Internal ops console routes (DESIGN.md §9), gated on the ``qonvo_admin`` claim.

Cross-tenant by nature, so every route uses ``get_system_db`` (BYPASSRLS
``qonvo_system`` role) rather than the tenant-scoped dependency. Every mutation
writes an ``audit_log`` row (§8, §9).
"""

from __future__ import annotations

import calendar
import secrets
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.config import (
    ConfigResponse,
    ConfigUpdateRequest,
    _apply_config_update,
    _config_to_dict,
)
from app.api.deps import get_system_db, get_waha, require_admin
from app.core.security import TokenClaims, hash_password
from app.models.enums import UserRole
from app.models.ops import UsageCounter
from app.models.tenant import AuditLog, Tenant, TenantConfig, TenantUser, User
from app.models.whatsapp import WhatsAppSession
from app.waha.client import WahaClient, WahaError

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateTenantRequest(BaseModel):
    name: str
    slug: str
    owner_email: EmailStr
    owner_name: str | None = None


class CreateTenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    owner_email: str
    temp_password: str


def _tenant_to_dict(row: Tenant) -> dict:
    return {"id": str(row.id), "name": row.name, "slug": row.slug, "status": row.status}


async def _audit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    claims: TokenClaims,
    action: str,
    target: str,
    meta: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=None,
            action=action,
            target=target,
            meta={"admin": claims.subject, **(meta or {})},
        )
    )


@router.get("/tenants")
async def list_tenants(
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> list[dict]:
    rows = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()
    return [_tenant_to_dict(t) for t in rows]


@router.post("/tenants", response_model=CreateTenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: CreateTenantRequest,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> CreateTenantResponse:
    """Provision a tenant end-to-end: tenant row + default config + owner user
    with a one-time temp password (DESIGN.md §9 tenant lifecycle)."""
    existing = (
        await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="slug already exists")

    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    await db.flush()

    db.add(TenantConfig(tenant_id=tenant.id))

    owner_email = body.owner_email.lower()
    temp_password = secrets.token_urlsafe(12)
    user = (await db.execute(select(User).where(User.email == owner_email))).scalar_one_or_none()
    if user is None:
        user = User(
            email=owner_email,
            hashed_password=hash_password(temp_password),
            full_name=body.owner_name,
        )
        db.add(user)
        await db.flush()
    else:
        user.hashed_password = hash_password(temp_password)

    db.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role=UserRole.owner))
    await _audit(
        db, tenant_id=tenant.id, claims=claims, action="tenant.create", target=str(tenant.id)
    )
    await db.flush()

    return CreateTenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        owner_email=user.email,
        temp_password=temp_password,
    )


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: UUID,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    return {**_tenant_to_dict(tenant), "config": _config_to_dict(config) if config else None}


@router.put("/tenants/{tenant_id}/config", response_model=ConfigResponse)
async def update_tenant_config(
    tenant_id: UUID,
    body: ConfigUpdateRequest,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> ConfigResponse:
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    config = (
        await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if config is None:
        config = TenantConfig(tenant_id=tenant_id)
        db.add(config)

    _apply_config_update(config, body)
    await _audit(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="tenant.config.update",
        target=str(tenant_id),
        meta={"fields": list(body.model_dump(exclude_unset=True))},
    )
    await db.flush()
    return _config_to_dict(config)


@router.get("/fleet")
async def fleet(
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
    waha: WahaClient = Depends(get_waha),
) -> list[dict]:
    """All WhatsApp sessions across every tenant, cross-checked against live
    WAHA status (DESIGN.md §9 fleet health)."""
    rows = (await db.execute(select(WhatsAppSession))).scalars().all()
    result = []
    for r in rows:
        try:
            info = await waha.get_session(r.session_name)
            live_status = info.get("status")
        except WahaError:
            live_status = "unreachable"
        result.append(
            {
                "id": str(r.id),
                "tenant_id": str(r.tenant_id),
                "session_name": r.session_name,
                "label": r.label,
                "status": r.status.value,
                "live_status": live_status,
                "engine": r.engine,
                "daily_cap": r.daily_cap,
                "warmup_stage": r.warmup_stage,
            }
        )
    return result


@router.get("/usage")
async def usage(
    month: str | None = Query(default=None, description="YYYY-MM"),
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> list[dict]:
    """Per-tenant usage rollup for manual invoicing (DESIGN.md §9, §13)."""
    filters = []
    if month is not None:
        try:
            year_str, month_str = month.split("-")
            year, mon = int(year_str), int(month_str)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="month must be YYYY-MM"
            ) from exc
        start = date(year, mon, 1)
        last_day = calendar.monthrange(year, mon)[1]
        end = date(year, mon, last_day)
        filters.extend([UsageCounter.day >= start, UsageCounter.day <= end])

    stmt = select(
        UsageCounter.tenant_id,
        func.sum(UsageCounter.messages_in).label("messages_in"),
        func.sum(UsageCounter.messages_out).label("messages_out"),
        func.sum(UsageCounter.voice_seconds).label("voice_seconds"),
        func.sum(UsageCounter.tokens).label("tokens"),
        func.sum(UsageCounter.cost).label("cost"),
    ).group_by(UsageCounter.tenant_id)
    if filters:
        stmt = stmt.where(*filters)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "tenant_id": str(r.tenant_id),
            "messages_in": r.messages_in or 0,
            "messages_out": r.messages_out or 0,
            "voice_seconds": r.voice_seconds or 0,
            "tokens": r.tokens or 0,
            "cost": float(r.cost or 0),
        }
        for r in rows
    ]


__all__ = ["router"]
