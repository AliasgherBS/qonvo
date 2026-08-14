"""Session management routes (DESIGN.md §10 onboarding, §5.1 webhook config).

JWT-authed, tenant-scoped. Creating a session provisions a WAHA session with a
per-session HMAC webhook secret and records the ``whatsapp_sessions`` mapping.
"""

from __future__ import annotations

import contextlib
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_waha, require_tenant
from app.core.config import settings
from app.models.enums import SessionStatus
from app.models.whatsapp import WhatsAppSession
from app.waha.client import WahaClient, WahaError

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    session_name: str = Field(min_length=1, max_length=255)
    label: str | None = None
    engine: str | None = None
    daily_cap: int = Field(default=settings.send_default_daily_cap, ge=1)
    warmup_stage: int = Field(default=0, ge=0, le=2)


class SessionResponse(BaseModel):
    id: UUID
    session_name: str
    label: str | None
    status: SessionStatus
    engine: str
    daily_cap: int
    warmup_stage: int


def _to_response(row: WhatsAppSession) -> SessionResponse:
    return SessionResponse(
        id=row.id,
        session_name=row.session_name,
        label=row.label,
        status=row.status,
        engine=row.engine,
        daily_cap=row.daily_cap,
        warmup_stage=row.warmup_stage,
    )


async def _get_row(db: AsyncSession, session_name: str) -> WhatsAppSession:
    row = (
        await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.session_name == session_name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return row


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    """This tenant's WhatsApp sessions with their last-known status. RLS scopes
    the rows to the caller's tenant; the status is kept fresh by the 60s
    ``session_health`` cron, so the owner's connection banner (§10) can flag a
    dropped session without a live WAHA round-trip per poll."""
    rows = (
        await db.execute(select(WhatsAppSession).order_by(WhatsAppSession.session_name))
    ).scalars().all()
    return [_to_response(r) for r in rows]


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> SessionResponse:
    existing = (
        await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.session_name == body.session_name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="session_name already exists")

    hmac_secret = secrets.token_urlsafe(32)
    engine = body.engine or settings.waha_default_engine

    row = WhatsAppSession(
        tenant_id=tenant_id,
        session_name=body.session_name,
        label=body.label,
        status=SessionStatus.starting,
        engine=engine,
        hmac_secret=hmac_secret,
        daily_cap=body.daily_cap,
        warmup_stage=body.warmup_stage,
    )
    db.add(row)
    await db.flush()

    webhook_config = {
        "url": settings.webhook_url,
        # message: pipeline; message.any: fromMe takeover; session.status/call: ops.
        "events": ["message", "message.any", "session.status", "call.received"],
        "hmac": {"key": hmac_secret},
        "retries": {"policy": "constant", "attempts": settings.webhook_retries},
    }
    try:
        await waha.create_session(
            body.session_name, webhooks=[webhook_config], engine=engine, start=True
        )
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc

    return _to_response(row)


@router.get("/{session_name}/status")
async def session_status(
    session_name: str,
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    row = await _get_row(db, session_name)
    try:
        info = await waha.get_session(session_name)
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc
    live = str(info.get("status", row.status.value)).upper()
    with contextlib.suppress(ValueError):
        row.status = SessionStatus(live)
    return {"session_name": session_name, "status": row.status.value, "waha": info}


@router.get("/{session_name}/qr")
async def session_qr(
    session_name: str,
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> Response:
    """QR passthrough — poll every ~15s until WORKING (DESIGN.md §10)."""
    await _get_row(db, session_name)
    try:
        image = await waha.get_qr(session_name)
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc
    return Response(content=image, media_type="image/png")
