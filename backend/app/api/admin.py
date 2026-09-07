"""Internal ops console routes (DESIGN.md §9), gated on the ``qonvo_admin`` claim.

Cross-tenant by nature, so every route uses ``get_system_db`` (BYPASSRLS
``qonvo_system`` role) rather than the tenant-scoped dependency. Every mutation
writes an ``audit_log`` row (§8, §9).
"""

from __future__ import annotations

import calendar
import contextlib
import secrets
from datetime import date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.storage import purge_tenant_files
from app.api.config import (
    ConfigResponse,
    ConfigUpdateRequest,
    _apply_config_update,
    _config_to_dict,
)
from app.api.deps import get_system_db, get_waha, require_admin
from app.billing.plans import PLANS
from app.billing.service import set_subscription
from app.core.logging import logger
from app.core.security import TokenClaims, hash_password
from app.models import TENANT_SCOPED_TABLES
from app.models.enums import SessionStatus, UserRole
from app.models.knowledge import KnowledgeSource
from app.models.ops import UsageCounter
from app.models.tenant import AuditLog, Tenant, TenantConfig, TenantUser, User
from app.models.whatsapp import WhatsAppSession
from app.services.auth import create_access_token
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
    return {
        "id": str(row.id),
        "name": row.name,
        "slug": row.slug,
        "status": row.status,
        "plan": row.plan,
        "trial_ends_at": row.trial_ends_at,
        "created_at": row.created_at,
    }


async def _owner_map(
    db: AsyncSession, tenant_ids: list[UUID]
) -> dict[UUID, tuple[str, str | None]]:
    """{tenant_id: (owner_email, owner_name)} for the owner of each tenant."""
    if not tenant_ids:
        return {}
    rows = (
        await db.execute(
            select(TenantUser.tenant_id, User.email, User.full_name)
            .join(User, User.id == TenantUser.user_id)
            .where(TenantUser.tenant_id.in_(tenant_ids), TenantUser.role == UserRole.owner)
        )
    ).all()
    return {r.tenant_id: (r.email, r.full_name) for r in rows}


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


@router.get("/health")
async def system_health(
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Live system health for the ops console: dependency readiness + the
    Redis-backed business/pipeline metric rollup (same numbers Prometheus scrapes,
    without needing to open Grafana)."""
    from sqlalchemy import text

    from app.core import obs
    from app.core.redis import get_redis

    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"fail: {type(exc).__name__}"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"fail: {type(exc).__name__}"
    checks["waha"] = "ok" if await waha.ping() else "fail: unreachable"

    return {
        "ready": all(v == "ok" for v in checks.values()),
        "checks": checks,
        "metrics": await obs.snapshot(),
    }


@router.get("/overview")
async def overview(
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """Platform-wide summary tiles: how many businesses exist, how many have a
    live WhatsApp session, how many have ingested knowledge, and 30-day volume.
    Cross-tenant, so it runs on the BYPASSRLS system session like the rest of
    /admin (DESIGN.md §9)."""
    since = date.today() - timedelta(days=30)

    async def count(stmt) -> int:
        return int(await db.scalar(stmt) or 0)

    return {
        "total_tenants": await count(select(func.count(Tenant.id))),
        # A business is "connected" when it has at least one WORKING session.
        "connected_tenants": await count(
            select(func.count(func.distinct(WhatsAppSession.tenant_id))).where(
                WhatsAppSession.status == SessionStatus.working
            )
        ),
        "total_sessions": await count(select(func.count(WhatsAppSession.id))),
        # Ingested = at least one source that finished ingestion (status "ready").
        "tenants_with_knowledge": await count(
            select(func.count(func.distinct(KnowledgeSource.tenant_id))).where(
                KnowledgeSource.status == "ready"
            )
        ),
        "knowledge_sources_ready": await count(
            select(func.count(KnowledgeSource.id)).where(KnowledgeSource.status == "ready")
        ),
        "messages_30d": await count(
            select(
                func.coalesce(
                    func.sum(UsageCounter.messages_in + UsageCounter.messages_out), 0
                )
            ).where(UsageCounter.day >= since)
        ),
        "cost_30d": float(
            await db.scalar(
                select(func.coalesce(func.sum(UsageCounter.cost), 0)).where(
                    UsageCounter.day >= since
                )
            )
            or 0
        ),
    }


@router.get("/usage/fleet")
async def fleet_usage(
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> list[dict]:
    """Every tenant's meters, worst first.

    This is the screen that catches a runaway tenant before the invoice does,
    which only works if the ordering does the noticing. Sorted by ``worst_state``
    and then by the highest single ratio, so the tenant most likely to be a
    problem is at the top without anyone having to scan.

    Uses the same ``tenant_usage`` the owner's own page uses. Deliberately N+1
    rather than one clever aggregate: a second implementation of these numbers
    is exactly what §4.3 warns against, and the operator's copy would be the one
    that drifted. Fleet size is small, and when it is not, the fix is a cache
    over this call rather than a different query.
    """
    from app.services.usage import tenant_usage

    tenant_ids = (await db.execute(select(Tenant.id, Tenant.name))).all()
    rows = []
    for tenant_id, name in tenant_ids:
        usage = await tenant_usage(db, tenant_id)
        row = usage.as_dict()
        row["tenant_name"] = name
        rows.append(row)

    severity = {"over": 0, "near": 1, "ok": 2}
    rows.sort(
        key=lambda r: (
            severity.get(r["worst_state"], 3),
            -max(
                m["ratio"]
                for m in (
                    r["messages"],
                    r["voice_minutes"],
                    r["seats"],
                    r["knowledge_sources"],
                    r["knowledge_chars"],
                    r["knowledge_upload_mb"],
                )
            ),
        )
    )
    return rows


@router.get("/tenants/{tenant_id}/usage")
async def tenant_usage_detail(
    tenant_id: UUID,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """One tenant's meters, identical to what its owner sees."""
    from app.services.usage import tenant_usage

    return (await tenant_usage(db, tenant_id)).as_dict()


@router.get("/tenants")
async def list_tenants(
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> list[dict]:
    rows = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()
    owners = await _owner_map(db, [t.id for t in rows])
    result = []
    for t in rows:
        email, full_name = owners.get(t.id, (None, None))
        result.append({**_tenant_to_dict(t), "owner_email": email, "owner_name": full_name})
    return result


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
    email, full_name = (await _owner_map(db, [tenant.id])).get(tenant.id, (None, None))
    return {
        **_tenant_to_dict(tenant),
        "owner_email": email,
        "owner_name": full_name,
        "config": _config_to_dict(config) if config else None,
    }


class UpdateTenantRequest(BaseModel):
    name: str | None = None
    status: str | None = None  # "active" | "suspended"
    plan: str | None = None  # "trial" | "paid"
    trial_ends_at: datetime | None = None


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: UUID,
    body: UpdateTenantRequest,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """Edit tenant lifecycle: name, status (active/suspended), plan, trial end.
    A ``suspended`` tenant's bot goes silent (enforced in the pipeline)."""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    fields = body.model_dump(exclude_unset=True)
    if fields.get("status") not in (None, "active", "suspended", "onboarding"):
        raise HTTPException(status_code=400, detail="status must be active or suspended")
    if fields.get("plan") not in (None, "trial", "paid"):
        raise HTTPException(status_code=400, detail="plan must be trial or paid")
    for key, value in fields.items():
        setattr(tenant, key, value)

    await _audit(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="tenant.update",
        target=str(tenant_id),
        meta={"fields": list(fields)},
    )
    await db.flush()
    email, full_name = (await _owner_map(db, [tenant.id])).get(tenant.id, (None, None))
    return {**_tenant_to_dict(tenant), "owner_email": email, "owner_name": full_name}


class SetSubscriptionRequest(BaseModel):
    plan_key: str
    status: str = "active"  # active | trialing | past_due | canceled
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


@router.put("/tenants/{tenant_id}/subscription")
async def set_tenant_subscription(
    tenant_id: UUID,
    body: SetSubscriptionRequest,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """Record what a tenant is on — the manual adapter's "mark paid".

    This is the same path a merchant-of-record webhook takes, so entitlements
    are rewritten from the plan catalogue either way and the two can never
    disagree about what a plan grants.
    """
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    if body.plan_key not in PLANS:
        raise HTTPException(status_code=400, detail="unknown plan")
    if body.status not in ("active", "trialing", "past_due", "canceled"):
        raise HTTPException(status_code=400, detail="unknown subscription status")

    sub = await set_subscription(
        db,
        tenant_id,
        {
            "plan_key": body.plan_key,
            "status": body.status,
            "provider": "manual",
            "current_period_end": body.current_period_end,
            "cancel_at_period_end": body.cancel_at_period_end,
        },
    )
    await _audit(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="tenant.subscription.set",
        target=str(tenant_id),
        meta={"plan_key": body.plan_key, "status": body.status},
    )
    await db.flush()
    return {
        "plan_key": sub.plan_key,
        "status": sub.status,
        "provider": sub.provider,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: UUID,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
    waha: WahaClient = Depends(get_waha),
) -> None:
    """Permanently offboard a tenant: tear down its WAHA sessions, purge every
    tenant-scoped row, remove orphaned users, then drop the tenant. Irreversible.
    (tenant_id has no FK cascade — RLS isolation — so this must be explicit.)"""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    # 1. Best-effort WAHA teardown — a missing/broken session must not block delete.
    names = (
        await db.execute(
            select(WhatsAppSession.session_name).where(WhatsAppSession.tenant_id == tenant_id)
        )
    ).scalars().all()
    for name in names:
        with contextlib.suppress(Exception):
            await waha.delete_session(name)

    # 2. Capture members before dropping memberships (to clean up orphaned users).
    user_ids = (
        await db.execute(select(TenantUser.user_id).where(TenantUser.user_id.isnot(None)).where(
            TenantUser.tenant_id == tenant_id
        ))
    ).scalars().all()

    # 3. Purge every tenant-scoped table (names are a trusted hardcoded constant).
    for table in TENANT_SCOPED_TABLES:
        await db.execute(text(f'DELETE FROM "{table}" WHERE tenant_id = :tid'), {"tid": tenant_id})

    # 4. Delete users left with no remaining membership (never a platform admin).
    for uid in user_ids:
        remaining = (
            await db.execute(
                select(func.count()).select_from(TenantUser).where(TenantUser.user_id == uid)
            )
        ).scalar_one()
        if remaining == 0:
            await db.execute(
                text("DELETE FROM users WHERE id = :uid AND is_qonvo_admin = false"), {"uid": uid}
            )

    # 5. Remove uploaded files. The database rows are gone, but the documents
    #    themselves live on a volume — leaving a business's price lists and
    #    contracts on the server after they offboard is a privacy problem, not
    #    just wasted disk.
    purge_tenant_files(tenant_id)

    # 6. Drop the tenant. (audit_log is tenant-scoped and just got purged, so log
    #    the offboarding to the ops log instead.)
    await db.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    logger.bind(tenant_id=str(tenant_id), actor=claims.subject).info(
        f"tenant offboarded (deleted): {tenant.name}"
    )


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
    names = dict((await db.execute(select(Tenant.id, Tenant.name))).all())
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
                "tenant_name": names.get(r.tenant_id),
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


_SESSION_ACTIONS = {"start", "stop", "restart", "logout"}


@router.post("/fleet/{session_name}/{action}")
async def fleet_session_action(
    session_name: str,
    action: str,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Control a tenant's WhatsApp session from the fleet console: start / stop /
    restart / logout. ``logout`` unlinks the phone (a fresh QR scan is needed to
    reconnect). Every action is audited against the owning tenant."""
    if action not in _SESSION_ACTIONS:
        raise HTTPException(
            status_code=400, detail=f"action must be one of {sorted(_SESSION_ACTIONS)}"
        )
    row = (
        await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.session_name == session_name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        if action == "start":
            await waha.start_session(session_name)
        elif action == "stop":
            await waha.stop_session(session_name)
        elif action == "logout":
            await waha.logout_session(session_name)
        elif action == "restart":
            await waha.stop_session(session_name)
            await waha.start_session(session_name)
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc
    await _audit(
        db, tenant_id=row.tenant_id, claims=claims, action=f"session.{action}", target=session_name
    )
    await db.flush()
    try:
        info = await waha.get_session(session_name)
        live_status = info.get("status")
    except WahaError:
        live_status = "unreachable"
    return {"session_name": session_name, "action": action, "live_status": live_status}


async def _tenant_owner(db: AsyncSession, tenant_id: UUID) -> User | None:
    return (
        await db.execute(
            select(User)
            .join(TenantUser, TenantUser.user_id == User.id)
            .where(TenantUser.tenant_id == tenant_id, TenantUser.role == UserRole.owner)
        )
    ).scalar_one_or_none()


class ResetPasswordResponse(BaseModel):
    owner_email: str
    temp_password: str


@router.post("/tenants/{tenant_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_owner_password(
    tenant_id: UUID,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> ResetPasswordResponse:
    """Mint a new one-time password for the tenant owner (support recovery when
    an owner is locked out). Returned once; the admin relays it out-of-band."""
    owner = await _tenant_owner(db, tenant_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="tenant owner not found")
    temp_password = secrets.token_urlsafe(12)
    owner.hashed_password = hash_password(temp_password)
    await _audit(
        db, tenant_id=tenant_id, claims=claims, action="user.reset_password", target=owner.email
    )
    await db.flush()
    return ResetPasswordResponse(owner_email=owner.email, temp_password=temp_password)


class ImpersonateResponse(BaseModel):
    access_token: str
    tenant_id: UUID
    owner_email: str


@router.post("/tenants/{tenant_id}/impersonate", response_model=ImpersonateResponse)
async def impersonate_tenant(
    tenant_id: UUID,
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> ImpersonateResponse:
    """Mint an owner-scoped JWT so support can "log in as" a tenant to reproduce
    an issue. The token carries the tenant owner's identity (NOT admin), so it is
    subject to normal RLS; the impersonation itself is audited."""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    owner = await _tenant_owner(db, tenant_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="tenant owner not found")
    token = create_access_token(
        subject=owner.email,
        tenant_id=tenant_id,
        role=UserRole.owner.value,
        is_qonvo_admin=False,
    )
    await _audit(
        db, tenant_id=tenant_id, claims=claims, action="tenant.impersonate", target=owner.email
    )
    await db.flush()
    return ImpersonateResponse(access_token=token, tenant_id=tenant_id, owner_email=owner.email)


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
    names = dict((await db.execute(select(Tenant.id, Tenant.name))).all())
    return [
        {
            "tenant_id": str(r.tenant_id),
            "tenant_name": names.get(r.tenant_id),
            "month": month or "all",
            "messages_in": r.messages_in or 0,
            "messages_out": r.messages_out or 0,
            "messages": (r.messages_in or 0) + (r.messages_out or 0),
            "voice_seconds": r.voice_seconds or 0,
            "tokens": r.tokens or 0,
            "cost": float(r.cost or 0),
        }
        for r in rows
    ]


__all__ = ["router"]
