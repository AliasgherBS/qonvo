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
from app.billing.service import get_subscription, set_subscription
from app.core.logging import logger
from app.core.redis import get_redis
from app.core.revocation import revoke_all_for_tenant
from app.core.security import TokenClaims, hash_password
from app.models import TENANT_SCOPED_TABLES
from app.models.billing import Subscription
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
    """Append one ops-console audit row.

    ``actor_email``/``actor_role`` are written with the same names
    ``app.services.audit`` uses for owner-side actions, because the reader
    (:func:`audit_log`) is one list over both and a row whose actor lives under
    a different key reads as anonymous. ``admin`` is kept alongside them: rows
    written before this existed only carry that key, and dropping it would make
    the console's own history unattributable.
    """
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=None,
            action=action,
            target=target,
            meta={
                "admin": claims.subject,
                "actor_email": claims.subject,
                "actor_role": "qonvo_admin",
                **(meta or {}),
            },
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
    """Every tenant, newest first.

    ``plan_key`` rides along with the coarse ``plan`` label because the label
    has two values and the catalogue has four: an operator scanning this list
    for "who is on Growth" cannot answer it from "paid". One extra select over
    a table with one row per tenant, rather than a per-row lookup.
    """
    rows = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()
    owners = await _owner_map(db, [t.id for t in rows])
    subs = dict(
        (await db.execute(select(Subscription.tenant_id, Subscription.plan_key))).all()
    )
    result = []
    for t in rows:
        email, full_name = owners.get(t.id, (None, None))
        result.append(
            {
                **_tenant_to_dict(t),
                "plan_key": subs.get(t.id),
                "owner_email": email,
                "owner_name": full_name,
            }
        )
    return result


@router.get("/plans")
async def list_plans(claims: TokenClaims = Depends(require_admin)) -> list[dict]:
    """The plan catalogue, so the console's plan picker offers the real keys.

    The console used to offer a two-state paid/trial toggle, which is how F3
    happened: a label with no catalogue entry behind it derives no entitlements.
    Served from ``app.billing.plans`` rather than restated in TypeScript, so a
    new tier appears in the picker by existing.
    """
    return [
        {"key": plan.key, "name": plan.name, "entitlements": plan.entitlements}
        for plan in PLANS.values()
    ]


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
    sub = await get_subscription(db, tenant_id)
    return {
        **_tenant_to_dict(tenant),
        "owner_email": email,
        "owner_name": full_name,
        # The plan *key*, its status and the entitlements actually in force.
        # All three, because F3 was precisely the case where the first two
        # agreed and the third had not been rewritten — an operator needs to be
        # able to see that from the tenant's own page.
        "subscription": _subscription_to_dict(sub) if sub else None,
        "entitlements": dict(config.entitlements or {}) if config else None,
        "config": _config_to_dict(config) if config else None,
    }


class UpdateTenantRequest(BaseModel):
    name: str | None = None
    status: str | None = None  # "active" | "suspended"
    trial_ends_at: datetime | None = None
    # Accepted only so it can be *refused* with an explanation.
    #
    # This field used to write ``tenants.plan`` straight through, which is
    # finding F3: it set a plan *label* while ``tenant_config.entitlements``
    # kept whatever the previous plan granted. An operator who took a bank
    # transfer and marked the customer paid left them capped at the trial's 300
    # messages, with the console reporting a paid plan. Silently ignoring the
    # field would reproduce the same outcome one layer quieter, so the route
    # names the endpoint that does it properly instead.
    plan: str | None = None


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
    if "plan" in fields:
        # ``tenants.plan`` is derived by ``apply_plan``, never assigned. See the
        # comment on the field.
        raise HTTPException(
            status_code=400,
            detail=(
                "plan is derived from the subscription, not set directly. "
                f"PUT /api/admin/tenants/{tenant_id}/subscription with a plan_key "
                f"({', '.join(sorted(PLANS))}) so entitlements are rewritten from "
                "the catalogue."
            ),
        )
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
    if fields.get("status") == "suspended":
        # Suspending stopped the bot and left every session in somebody's hand
        # working (teardown X6). Revoked at the tenant level rather than by
        # walking its members: enumerating them would race with a membership
        # change, and the point is to stop the workspace, not a person.
        await revoke_all_for_tenant(get_redis(), tenant_id)
    email, full_name = (await _owner_map(db, [tenant.id])).get(tenant.id, (None, None))
    return {**_tenant_to_dict(tenant), "owner_email": email, "owner_name": full_name}


def _subscription_to_dict(sub: Subscription) -> dict:
    return {
        "plan_key": sub.plan_key,
        "plan_name": PLANS[sub.plan_key].name if sub.plan_key in PLANS else sub.plan_key,
        "status": sub.status,
        "provider": sub.provider,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }


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
    return _subscription_to_dict(sub)


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
        # Names the admin behind the session. Without it the token carried the
        # owner's identity and nothing else, so the act of impersonating was
        # audited and every action taken inside the session was attributed to
        # the customer (teardown X4).
        acting_as=claims.subject,
    )
    await _audit(
        db, tenant_id=tenant_id, claims=claims, action="tenant.impersonate", target=owner.email
    )
    await db.flush()
    return ImpersonateResponse(access_token=token, tenant_id=tenant_id, owner_email=owner.email)


#: Ceiling on one page of audit rows. High enough that "show me everything this
#: tenant did" is one request, low enough that a console with a year of history
#: cannot ask the API for all of it by accident.
_AUDIT_PAGE_MAX = 200


def _audit_actor(meta: dict) -> tuple[str | None, str | None, str | None]:
    """(actor_email, actor_role, impersonated_by) out of a row's ``meta``.

    Three writers put the actor in ``meta``: ``app.services.audit`` (owner-side)
    uses ``actor_email``/``actor_role``, this module's ``_audit`` now writes the
    same pair, and rows written before that carry only ``admin``. Reading all
    three here means the console shows one list instead of one list per writer.
    """
    email = meta.get("actor_email") or meta.get("admin")
    role = meta.get("actor_role") or ("qonvo_admin" if meta.get("admin") else None)
    return email, role, meta.get("impersonated_by")


@router.get("/audit")
async def audit_log(
    tenant_id: UUID | None = Query(default=None, description="Only this tenant's rows"),
    actor: str | None = Query(default=None, description="Substring match on the actor's email"),
    action: str | None = Query(default=None, description="Substring match on the action"),
    limit: int = Query(default=50, ge=1, le=_AUDIT_PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    claims: TokenClaims = Depends(require_admin),
    db: AsyncSession = Depends(get_system_db),
) -> dict:
    """Read the audit trail (finding A2).

    ``audit_log`` had been written by the admin console, by activation and by
    every owner-side action since X8, and read by nothing: there was no route
    and no page, so "who suspended this tenant" needed psql. This is the read
    side of a table that was already being populated.

    Newest first, because the question is almost always about something that
    just happened. Filters are substring matches on the actor and the action
    rather than exact ones: an operator knows "hass..." and "suspend", not
    ``hassan@example.com`` and ``tenant.update``.
    """
    conditions = []
    if tenant_id is not None:
        conditions.append(AuditLog.tenant_id == tenant_id)
    if action:
        conditions.append(AuditLog.action.ilike(f"%{action}%"))
    if actor:
        needle = f"%{actor}%"
        # The actor lives in three places, so the filter has to look in all
        # three or it silently hides rows: ``meta`` for both admin writers, and
        # the ``users`` row for owner-side actions where the id is the record.
        conditions.append(
            AuditLog.meta["actor_email"].astext.ilike(needle)
            | AuditLog.meta["admin"].astext.ilike(needle)
            | AuditLog.actor_user_id.in_(select(User.id).where(User.email.ilike(needle)))
        )

    total = int(
        await db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    )
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(*conditions)
                # id as the tiebreak: several rows of one request share a
                # timestamp to the microsecond, and an unstable sort makes
                # paging repeat and skip rows.
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    tenant_names = dict((await db.execute(select(Tenant.id, Tenant.name))).all())
    # Owner-side rows name the actor by id. One lookup for the whole page.
    actor_ids = [r.actor_user_id for r in rows if r.actor_user_id is not None]
    actor_emails: dict[UUID, str] = {}
    if actor_ids:
        actor_emails = dict(
            (await db.execute(select(User.id, User.email).where(User.id.in_(actor_ids)))).all()
        )

    items = []
    for row in rows:
        meta = dict(row.meta or {})
        email, role, impersonated_by = _audit_actor(meta)
        items.append(
            {
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "tenant_name": tenant_names.get(row.tenant_id),
                "action": row.action,
                "target": row.target,
                "created_at": row.created_at,
                "actor_email": email or actor_emails.get(row.actor_user_id),
                "actor_role": role,
                "impersonated_by": impersonated_by,
                # Whatever the writer added beyond the actor: changed field
                # names, a plan key, a readiness snapshot.
                "meta": {
                    k: v
                    for k, v in meta.items()
                    if k not in ("admin", "actor_email", "actor_role", "impersonated_by")
                },
            }
        )

    return {"items": items, "total": total, "limit": limit, "offset": offset}


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
