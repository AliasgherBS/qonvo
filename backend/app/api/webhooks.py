"""WAHA webhook ingress (DESIGN.md §5.1–5.2).

Pipeline: HMAC verify → tenant resolution via ``whatsapp_sessions`` → filter →
dedupe → debounce buffer → 200 fast. Heavy work happens in the arq worker.
"""

from __future__ import annotations

import json

from arq import ArqRedis
from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select

from app.agent.debounce import add_fragment, is_duplicate
from app.api.deps import get_arq
from app.core.config import settings
from app.core.logging import logger
from app.core.redis import get_redis
from app.core.security import verify_waha_hmac
from app.core.tenancy import system_session
from app.models.whatsapp import WhatsAppSession

router = APIRouter(tags=["webhooks"])

# Non-user chat suffixes we never process (DESIGN.md §5.1).
_IGNORED_SUFFIXES = ("@g.us", "@newsletter", "@broadcast")
_IGNORED_EXACT = ("status@broadcast",)


def is_processable_chat_id(chat_id: str | None) -> bool:
    """Only 1:1 user chats (``@c.us``) are processed by the agent pipeline."""
    if not chat_id:
        return False
    if chat_id in _IGNORED_EXACT:
        return False
    if any(chat_id.endswith(suffix) for suffix in _IGNORED_SUFFIXES):
        return False
    return chat_id.endswith("@c.us")


def _extract(payload: dict) -> dict:
    """Pull the inner message object from a WAHA webhook envelope."""
    return payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}


async def _resolve_session(session_name: str) -> WhatsAppSession | None:
    async with system_session() as db:
        result = await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.session_name == session_name)
        )
        return result.scalar_one_or_none()


@router.post("/webhooks/waha")
async def waha_webhook(
    request: Request,
    response: Response,
    x_webhook_hmac: str | None = Header(default=None),
    arq: ArqRedis = Depends(get_arq),
) -> dict:
    raw = await request.body()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {"status": "bad_request", "detail": "invalid JSON"}

    session_name = payload.get("session")
    event = payload.get("event")

    # --- Tenant resolution (needed to pick the per-session HMAC secret) ---
    session_row = await _resolve_session(session_name) if session_name else None
    if session_row is None:
        logger.bind(session=session_name, event=event).warning("webhook for unknown session")
        return {"status": "ignored", "reason": "unknown_session"}

    # --- HMAC verify against the raw body (§5.1) ---
    secret = session_row.hmac_secret or settings.waha_hmac_secret
    if not verify_waha_hmac(raw, x_webhook_hmac, secret):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"status": "unauthorized", "detail": "HMAC verification failed"}

    tenant_id = str(session_row.tenant_id)
    inner = _extract(payload)
    from_me = bool(inner.get("fromMe", False))
    chat_id = inner.get("from")
    message_id = inner.get("id")
    bound = logger.bind(session=session_name, event=event, tenant_id=tenant_id)

    # --- Event routing (§5.1) ---
    if event == "session.status":
        bound.info(f"session status event: {inner.get('status')}")
        return {"status": "ok"}

    if event == "call.received":
        # Reject-and-nudge is a Phase 1 behavior; log the call for now.
        bound.info("call.received (auto-reply deferred to Phase 1)")
        return {"status": "ok"}

    if event == "message.any":
        # Subscribed only to detect owner fromMe takeover (§5.5); never processed.
        if from_me and is_processable_chat_id(chat_id):
            bound.info("owner fromMe reply detected — takeover signal")
        return {"status": "ok"}

    if event != "message":
        bound.debug("ignoring non-message event")
        return {"status": "ignored", "reason": "event_not_handled"}

    # --- message event → pipeline ---
    if from_me:
        return {"status": "ignored", "reason": "from_me"}  # never process our own sends
    if not is_processable_chat_id(chat_id):
        return {"status": "ignored", "reason": "non_user_chat"}
    if not message_id:
        return {"status": "ignored", "reason": "no_message_id"}

    redis_client = get_redis()

    # --- Dedupe (Redis SETNX 24h + messages.wa_message_id unique) (§5.1) ---
    if await is_duplicate(redis_client, message_id, settings.dedupe_ttl_seconds):
        bound.info(f"duplicate message ignored: {message_id}")
        return {"status": "ignored", "reason": "duplicate"}

    # --- Debounce buffer (§5.2) ---
    window = session_config_window(session_row)
    fragment = {
        "message_id": message_id,
        "type": inner.get("type", "text"),
        "body": inner.get("body", "") or "",
        "media_url": inner.get("mediaUrl") or (inner.get("media") or {}).get("url"),
        "timestamp": inner.get("timestamp"),
    }
    generation = await add_fragment(
        redis_client, session_name, chat_id, fragment, window_seconds=window
    )
    await arq.enqueue_job(
        "close_debounce_window",
        session_name,
        chat_id,
        generation,
        tenant_id,
        _defer_by=window,
    )

    bound.info(f"buffered fragment gen={generation} msg={message_id}")
    return {"status": "buffered", "generation": generation}


def session_config_window(session_row: WhatsAppSession) -> float:
    """Debounce window seconds for a session (tenant override lands in Phase 1)."""
    return settings.debounce_window_seconds
