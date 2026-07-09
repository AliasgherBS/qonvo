"""arq worker: debounce close + per-conversation processing (DESIGN.md §5.2–5.4).

Guarantees:
- **Serialization**: a per-conversation Redis lock; a job that can't acquire it
  re-enqueues itself with a delay instead of running concurrently.
- **Staleness guard**: fragments older than the threshold on reconnect are logged
  and answered with a single catch-up reply, not one-by-one.
- **Reliability**: arq retries with exponential backoff (``job_max_retries``);
  the final failure writes a ``failed_jobs`` DLQ row.
"""

from __future__ import annotations

import time
from typing import Any

from arq import Retry
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis import get_redis
from app.core.tenancy import tenant_session
from app.models.ops import FailedJob
from app.waha.client import WahaClient
from app.waha.send_gateway import SendGateway
from app.workers.lock import acquire_conversation_lock
from app.workers.pipeline import InboundFragment, run_pipeline


def _conversation_lock_id(session: str, chat_id: str) -> str:
    """Phase 0 conversation key. Phase 1 swaps this for the DB ``conversation_id``
    once conversation-row lifecycle (§5.4) is implemented."""
    return f"{session}:{chat_id}"


def _is_stale(fragments: list[InboundFragment], *, now: float) -> bool:
    timestamps = [f.timestamp for f in fragments if f.timestamp is not None]
    if not timestamps:
        return False
    newest = max(timestamps)
    return (now - newest) > settings.staleness_threshold_seconds


async def close_debounce_window(
    ctx: dict[str, Any],
    session: str,
    chat_id: str,
    generation: int,
    tenant_id: str | None,
) -> None:
    """Delayed job: if still the current generation, drain the buffer and enqueue
    a single coalesced ``process_conversation`` job (§5.2)."""
    from app.agent.debounce import close_window

    redis_client = get_redis()
    fragments = await close_window(redis_client, session, chat_id, generation)
    if not fragments:
        return  # a newer fragment reset the window — no-op
    await ctx["redis"].enqueue_job(
        "process_conversation",
        session,
        chat_id,
        fragments,
        tenant_id,
    )


async def process_conversation(
    ctx: dict[str, Any],
    session: str,
    chat_id: str,
    fragments: list[dict],
    tenant_id: str | None,
) -> None:
    """Process one coalesced conversation turn under a per-conversation lock."""
    parsed = [InboundFragment(**f) for f in fragments]
    conv_id = _conversation_lock_id(session, chat_id)
    redis_client = get_redis()
    bound = logger.bind(session=session, chat_id=chat_id, tenant_id=tenant_id)

    lock = await acquire_conversation_lock(
        redis_client, conv_id, ttl_ms=settings.conversation_lock_ttl_ms
    )
    if not lock.acquired:
        # Someone else holds it — re-enqueue a fresh job (doesn't burn retries).
        await ctx["redis"].enqueue_job(
            "process_conversation",
            session,
            chat_id,
            fragments,
            tenant_id,
            _defer_by=settings.conversation_lock_retry_delay_seconds,
        )
        return

    try:
        catch_up = _is_stale(parsed, now=time.time())
        if catch_up:
            bound.warning("stale backlog detected — sending catch-up reply only")
        gateway: SendGateway = ctx["send_gateway"]
        if tenant_id is None:
            bound.error("cannot process without a resolved tenant_id")
            return
        await run_pipeline(
            parsed,
            session=session,
            chat_id=chat_id,
            tenant_id=tenant_id,
            send_gateway=gateway,
            catch_up=catch_up,
        )
    except Exception as exc:  # noqa: BLE001 — retry/DLQ boundary
        job_try = ctx.get("job_try", 1)
        if job_try >= settings.job_max_retries:
            bound.error(f"job exhausted retries, writing DLQ row: {exc}")
            await _write_failed_job(tenant_id, session, chat_id, fragments, exc, job_try)
            return
        raise Retry(defer=2**job_try) from exc
    finally:
        await lock.release()


async def _write_failed_job(
    tenant_id: str | None,
    session: str,
    chat_id: str,
    fragments: list[dict],
    exc: Exception,
    attempts: int,
) -> None:
    if tenant_id is None:
        logger.error("cannot write DLQ row without tenant_id")
        return
    import uuid

    async with tenant_session(uuid.UUID(tenant_id)) as db:
        db.add(
            FailedJob(
                tenant_id=uuid.UUID(tenant_id),
                function="process_conversation",
                payload={"session": session, "chat_id": chat_id, "fragments": fragments},
                error=str(exc),
                attempts=attempts,
            )
        )


# --------------------------------------------------------------------------- #
# arq wiring
# --------------------------------------------------------------------------- #
async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    waha = WahaClient()
    ctx["waha"] = waha
    ctx["send_gateway"] = SendGateway(waha, get_redis())
    logger.info("worker started")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    waha: WahaClient | None = ctx.get("waha")
    if waha is not None:
        await waha.aclose()
    logger.info("worker stopped")


class WorkerSettings:
    functions = [process_conversation, close_debounce_window]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = settings.job_max_retries
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
