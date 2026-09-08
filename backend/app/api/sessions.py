"""Session management routes (DESIGN.md §10 onboarding, §5.1 webhook config).

JWT-authed, tenant-scoped. Creating a session provisions a WAHA session with a
per-session HMAC webhook secret and records the ``whatsapp_sessions`` mapping.

These routes are also the owner's *status* surface, not only its setup one
(teardown W1): the number is the product, so the page that says whether it is
plugged in needs the linked number, the live state, when it last saw traffic,
and the two recovery controls. Before this, a dropped session could only be
restarted from the internal admin console, which made every disconnection a
support ticket.
"""

from __future__ import annotations

import contextlib
import re
import secrets
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_claims,
    get_db,
    get_waha,
    require_owner,
    require_tenant,
    require_verified_owner,
)
from app.core.config import settings
from app.core.security import TokenClaims
from app.models.conversation import Conversation
from app.models.enums import SessionStatus
from app.models.whatsapp import WhatsAppSession
from app.services import audit
from app.waha.client import WahaClient, WahaError

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    """Nothing here is required.

    ``session_name`` used to be, and the form asked a salon owner to invent one
    with the example ``main-support-line`` (teardown W2). It is the WAHA session
    key: an internal identifier, and one this route derives anyway (see
    :func:`derive_session_name`), so asking for it bought nothing. It is still
    *accepted* — older clients post it — but it is treated as a label and never
    used verbatim.
    """

    label: str | None = Field(default=None, max_length=255)
    session_name: str | None = Field(default=None, max_length=255)
    engine: str | None = None
    daily_cap: int = Field(default=settings.send_default_daily_cap, ge=1)
    # New numbers warm up by default (§5.6): 50/day for a week, then 150/day.
    # Pass 0 explicitly when connecting a number that is already established.
    warmup_stage: int = Field(default=1, ge=0, le=2)

    @property
    def display_label(self) -> str:
        """What a human would call this number."""
        return (self.label or self.session_name or DEFAULT_SESSION_LABEL).strip() or (
            DEFAULT_SESSION_LABEL
        )


DEFAULT_SESSION_LABEL = "WhatsApp number"


def derive_session_name(label: str) -> str:
    """The WAHA session key for ``label``.

    The key is GLOBALLY unique (one WAHA serves every tenant). A tenant-scoped
    uniqueness check (RLS) would miss a clash with another tenant's session and
    the insert would 500, so the name carries a random suffix rather than being
    checked for availability.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:24] or "wa"
    return f"{slug}-{secrets.token_hex(4)}"


class SessionResponse(BaseModel):
    id: UUID
    session_name: str
    label: str | None
    status: SessionStatus
    engine: str
    daily_cap: int
    warmup_stage: int
    # The linked number, as WhatsApp reports it. NULL until the session has been
    # WORKING at least once and someone has polled its status.
    phone_number: str | None = None
    # When the number was linked, and when it last saw a conversation. "Last
    # event" is derived from ``conversations.last_activity_at`` rather than a new
    # column: the pipeline already stamps it on every inbound and outbound
    # message, so a separate counter could only ever disagree with it.
    connected_at: datetime | None = None
    last_event_at: datetime | None = None


def _to_response(
    row: WhatsAppSession, last_event_at: datetime | None = None
) -> SessionResponse:
    return SessionResponse(
        id=row.id,
        session_name=row.session_name,
        label=row.label,
        status=row.status,
        engine=row.engine,
        daily_cap=row.daily_cap,
        warmup_stage=row.warmup_stage,
        phone_number=row.phone_number,
        connected_at=row.created_at,
        last_event_at=last_event_at,
    )


async def _last_event_at(db: AsyncSession, session_ids: list[UUID]) -> dict[UUID, datetime]:
    """Newest conversation activity per session. One grouped query, not N."""
    if not session_ids:
        return {}
    rows = (
        await db.execute(
            select(Conversation.session_id, func.max(Conversation.last_activity_at))
            .where(Conversation.session_id.in_(session_ids))
            .group_by(Conversation.session_id)
        )
    ).all()
    return {session_id: seen for session_id, seen in rows if seen is not None}


async def _get_row(db: AsyncSession, session_name: str) -> WhatsAppSession:
    row = (
        await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.session_name == session_name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return row


async def _resync_status(
    row: WhatsAppSession, waha: WahaClient, fallback: SessionStatus
) -> None:
    """Store what WAHA says the session is now, not what we assume.

    A restart and a logout both land somewhere the client cannot predict
    (STARTING, STOPPED or SCAN_QR_CODE depending on the engine and on how the
    phone dropped), and guessing would put a state on the page that the next
    poll contradicts. ``fallback`` covers WAHA being unreachable for the read,
    which must not turn a successful action into a 502.
    """
    try:
        info = await waha.get_session(row.session_name)
    except WahaError:
        row.status = fallback
        return
    live = str(info.get("status", fallback.value)).upper()
    try:
        row.status = SessionStatus(live)
    except ValueError:
        row.status = fallback


def _adopt_phone_number(row: WhatsAppSession, info: dict) -> None:
    """Record the linked number from WAHA's ``me`` block.

    Only ``@c.us`` is trusted here. Modern accounts *message* from ``@lid``
    (see CLAUDE.md), and a lid is an opaque linked id, not a phone number — so
    rendering its user part as the business's number would print a plausible
    wrong number on the one page whose job is to say which number is live.
    """
    me = info.get("me")
    if not isinstance(me, dict):
        return
    wid = str(me.get("id") or "")
    if wid.endswith("@c.us"):
        row.phone_number = wid.split("@", 1)[0][:32]


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
    seen = await _last_event_at(db, [r.id for r in rows])
    return [_to_response(r, seen.get(r.id)) for r in rows]


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    # Owner, and the address confirmed: this is the step that turns a signup
    # into a live business identity on somebody's real phone number, so it is
    # the one thing an unconfirmed account is held back from (teardown X2).
    tenant_id: UUID = Depends(require_verified_owner),
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> SessionResponse:
    label = body.display_label
    session_name = derive_session_name(label)

    hmac_secret = secrets.token_urlsafe(32)
    engine = body.engine or settings.waha_default_engine

    row = WhatsAppSession(
        tenant_id=tenant_id,
        session_name=session_name,
        label=label,
        status=SessionStatus.starting,
        engine=engine,
        hmac_secret=hmac_secret,
        daily_cap=body.daily_cap,
        warmup_stage=body.warmup_stage,
    )
    db.add(row)
    await db.flush()
    # ``created_at`` is a server default, so it is expired after the flush and
    # reading it would trigger lazy IO outside an await (MissingGreenlet).
    await db.refresh(row, ["created_at"])

    webhook_config = {
        "url": settings.webhook_url,
        # message: pipeline; message.any: fromMe takeover; session.status/call: ops.
        "events": ["message", "message.any", "session.status", "call.received"],
        "hmac": {"key": hmac_secret},
        "retries": {"policy": "constant", "attempts": settings.webhook_retries},
    }
    try:
        await waha.create_session(
            session_name, webhooks=[webhook_config], engine=engine, start=True
        )
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc

    # Recorded after WAHA accepts it, so the row means "a number was linked"
    # rather than "somebody tried". This is the action that points the
    # business's real WhatsApp number at us, which makes it the one worth being
    # able to look up later.
    await audit.record(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="whatsapp_session_created",
        target=session_name,
        meta={"label": label, "engine": engine},
    )

    return _to_response(row)


@router.get("/{session_name}/status")
async def session_status(
    session_name: str,
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Live state for one session, plus everything the status page renders.

    Returns the stored fields alongside WAHA's answer so the page needs one
    poll rather than a poll and a list call.
    """
    row = await _get_row(db, session_name)
    try:
        info = await waha.get_session(session_name)
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc
    live = str(info.get("status", row.status.value)).upper()
    with contextlib.suppress(ValueError):
        row.status = SessionStatus(live)
    _adopt_phone_number(row, info)
    seen = await _last_event_at(db, [row.id])
    return {
        "session_name": session_name,
        "status": row.status.value,
        "label": row.label,
        "phone_number": row.phone_number,
        "connected_at": row.created_at.isoformat() if row.created_at else None,
        "last_event_at": (
            seen[row.id].isoformat() if seen.get(row.id) is not None else None
        ),
        "waha": info,
    }


@router.post("/{session_name}/restart")
async def restart_session(
    session_name: str,
    # Owner, but not email-verified-gated: this is the recovery action for a
    # session that is already linked, and holding it back from an owner whose
    # address bounced would leave them with a dead rep and no control. It does
    # not hand out a pairing credential — a restart reuses the stored auth.
    tenant_id: UUID = Depends(require_owner),
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Stop then start the session. A bare start is a no-op on a FAILED session
    (WAHA still believes it is running), which is why the client cannot just
    call start (§12.1)."""
    row = await _get_row(db, session_name)
    try:
        await waha.restart_session(session_name)
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc
    await _resync_status(row, waha, SessionStatus.starting)
    await audit.record(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="whatsapp_session_restarted",
        target=session_name,
    )
    return {"session_name": session_name, "status": row.status.value}


@router.post("/{session_name}/logout")
async def logout_session(
    session_name: str,
    # Verified owner, like create and the QR: logging out drops the link to the
    # business's number and the only way back is a fresh QR scan, so it is the
    # same act of authority as linking it in the first place.
    tenant_id: UUID = Depends(require_verified_owner),
    claims: TokenClaims = Depends(get_claims),
    db: AsyncSession = Depends(get_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Unlink the phone. The session row is kept, so re-linking scans a QR into
    the same session rather than creating a second one."""
    row = await _get_row(db, session_name)
    try:
        await waha.logout_session(session_name)
    except WahaError as exc:
        raise HTTPException(status_code=502, detail=f"WAHA error: {exc.detail}") from exc
    await _resync_status(row, waha, SessionStatus.starting)
    # The number is no longer linked, so keeping it on the page would be the one
    # thing this page exists to get right, wrong.
    row.phone_number = None
    await audit.record(
        db,
        tenant_id=tenant_id,
        claims=claims,
        action="whatsapp_session_logged_out",
        target=session_name,
    )
    return {"session_name": session_name, "status": row.status.value}


@router.get("/{session_name}/qr")
async def session_qr(
    session_name: str,
    # Owner-only. RLS already scopes this to the caller's tenant, so it was
    # never a cross-tenant leak, but a pairing QR is the credential that links
    # a WhatsApp account: whoever scans it controls the number. That is not a
    # staff act, and it was reachable by any member.
    # Confirmed as well as owner: the QR is the whole of the linking step, so
    # gating creation and leaving this open would gate nothing.
    _owner: UUID = Depends(require_verified_owner),
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
