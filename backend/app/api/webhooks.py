"""WAHA webhook ingress (DESIGN.md §5.1–5.2).

Pipeline: HMAC verify → tenant resolution via ``whatsapp_sessions`` → filter →
dedupe → debounce buffer → 200 fast. Heavy work happens in the arq worker.
"""

from __future__ import annotations

import json

from arq import ArqRedis
from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select

from app.agent.debounce import add_fragment, is_duplicate, is_rate_limited
from app.api.deps import get_arq
from app.core import obs
from app.core.config import settings
from app.core.logging import logger
from app.core.redis import get_redis
from app.core.security import verify_waha_hmac
from app.core.tenancy import system_session
from app.models.whatsapp import WhatsAppSession
from app.services.takeover import implicit_takeover
from app.waha.send_gateway import is_own_send, own_send_fingerprint

router = APIRouter(tags=["webhooks"])

# Non-user chat suffixes we never process (DESIGN.md §5.1).
_IGNORED_SUFFIXES = ("@g.us", "@newsletter", "@broadcast")
_IGNORED_EXACT = ("status@broadcast",)
# 1:1 user chats: classic phone-number JIDs (@c.us) AND WhatsApp's newer
# privacy-preserving Linked IDs (@lid) — modern accounts send from @lid.
_USER_CHAT_SUFFIXES = ("@c.us", "@lid")


def is_processable_chat_id(chat_id: str | None) -> bool:
    """Only 1:1 user chats (``@c.us`` / ``@lid``) reach the agent pipeline."""
    if not chat_id:
        return False
    if chat_id in _IGNORED_EXACT:
        return False
    if any(chat_id.endswith(suffix) for suffix in _IGNORED_SUFFIXES):
        return False
    return any(chat_id.endswith(suffix) for suffix in _USER_CHAT_SUFFIXES)


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
        await obs.incr("qonvo_webhook_unauthorized_total")
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
        # Subscribed only to detect owner fromMe takeover (§5.5); never processed
        # through the agent pipeline. Two subtleties (both caught live):
        # 1. Our own gateway sends are ALSO fromMe — skip anything we sent
        #    ourselves, or the bot pauses itself after every reply.
        # 2. On a fromMe message the customer chat is ``to``, not ``from``.
        if from_me:
            takeover_chat = inner.get("to") or chat_id
            own = await is_own_send(get_redis(), own_send_fingerprint(message_id))
            if not own and is_processable_chat_id(takeover_chat):
                async with system_session() as db:
                    await implicit_takeover(
                        db,
                        tenant_id=session_row.tenant_id,
                        session_id=session_row.id,
                        chat_id=takeover_chat,
                    )
                bound.info("owner fromMe reply detected — implicit takeover applied")
        return {"status": "ok"}

    if event != "message":
        bound.debug("ignoring non-message event")
        return {"status": "ignored", "reason": "event_not_handled"}

    # --- message event → pipeline ---
    # Every drop is logged: a silently ignored message reads as "bot is down"
    # to the business owner, so the reason must be greppable in ops.
    if from_me:
        bound.info("ignored message: from_me (our own send)")
        return {"status": "ignored", "reason": "from_me"}
    if not is_processable_chat_id(chat_id):
        bound.info(f"ignored message: non_user_chat (from={chat_id!r}, keys={sorted(inner)})")
        return {"status": "ignored", "reason": "non_user_chat"}
    if not message_id:
        bound.info(f"ignored message: no_message_id (keys={sorted(inner)})")
        return {"status": "ignored", "reason": "no_message_id"}

    redis_client = get_redis()

    # --- Dedupe (Redis SETNX 24h + messages.wa_message_id unique) (§5.1) ---
    if await is_duplicate(redis_client, message_id, settings.dedupe_ttl_seconds):
        bound.info(f"duplicate message ignored: {message_id}")
        return {"status": "ignored", "reason": "duplicate"}

    # --- Rate limit: drop a single customer flooding the number (bounds LLM spend) ---
    if await is_rate_limited(
        redis_client,
        session_name,
        chat_id,
        limit=settings.inbound_rate_limit,
        window_seconds=settings.inbound_rate_window_seconds,
    ):
        await obs.incr("qonvo_pipeline_gate_total", {"gate": "rate_limited"})
        bound.info(f"rate limited: {chat_id}")
        return {"status": "ignored", "reason": "rate_limited"}

    # --- Debounce buffer (§5.2) ---
    window = session_config_window(session_row)
    media = inner.get("media") if isinstance(inner.get("media"), dict) else {}
    mimetype = (media.get("mimetype") or "") if media else ""
    # NOWEB omits `type` on voice notes (WEBJS set it), so derive it from the
    # media mimetype — an audio/* attachment is a voice message to transcribe.
    msg_type = inner.get("type")
    if not msg_type and mimetype.startswith("audio/"):
        msg_type = "voice"
    fragment = {
        "message_id": message_id,
        "type": msg_type or "text",
        "body": inner.get("body", "") or "",
        "media_url": inner.get("mediaUrl") or (media.get("url") if media else None),
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
