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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
from arq import Retry
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis import get_redis
from app.core.tenancy import tenant_session
from app.models.enums import NotificationType
from app.models.ops import FailedJob
from app.services.notifications import notify
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
            waha=ctx.get("waha"),
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
        # The row on its own was not enough (teardown F2).
        #
        # Retry worked and the dead-letter row was written, and two customer
        # messages still went unanswered for four days, because nothing reads
        # this table: no notification, no flag, no page. From the owner's side
        # it looked like a customer who went quiet.
        #
        # Both live rows were HTTP 429 "exceeded your current quota" from the
        # LLM provider, which is worth saying in the notification: the owner
        # can act on "we could not reach the AI provider" and cannot act on a
        # stack trace.
        await notify(
            db,
            tenant_id=uuid.UUID(tenant_id),
            title="A customer message could not be answered",
            body=(
                f"We tried {attempts} times and could not generate a reply for "
                f"{_readable_chat(chat_id)}. The message is in your inbox and "
                f"nobody has replied to it. Reason: {_readable_job_error(exc)}"
            ),
            type=NotificationType.escalation,
            meta={
                "chat_id": chat_id,
                "reason": _readable_job_error(exc),
                "attempts": attempts,
                "failed_job": True,
            },
        )
    from app.core import obs

    await obs.incr("qonvo_job_failures_total", {"function": "process_conversation"})


# --------------------------------------------------------------------------- #
# arq wiring
# --------------------------------------------------------------------------- #

def _readable_chat(chat_id: str) -> str:
    """A chat id an owner can recognise, without importing the inbox's helper.

    Reuses the API's formatter so the notification and the inbox cannot
    disagree about what a customer is called.
    """
    from app.api.conversations import format_phone_number

    return format_phone_number(chat_id) or chat_id


def _readable_job_error(exc: Exception) -> str:
    """One line an owner can act on, from an exception written for us.

    The two real failures were a provider quota refusal, which is actionable
    (top up, or change provider) in a way that "DBAPIError" is not.
    """
    text = str(exc)
    lowered = text.lower()
    if "429" in text and "quota" in lowered:
        return "the AI provider refused the request because its quota is exhausted"
    if "429" in text:
        return "the AI provider rate-limited us"
    if "401" in text or "403" in text:
        return "the AI provider rejected our credentials"
    if "timeout" in lowered or "timed out" in lowered:
        return "the AI provider did not respond in time"
    return f"an internal error: {text[:120]}"


async def ingest_knowledge_source(ctx: dict[str, Any], source_id: str, tenant_id: str) -> None:
    """Chunk + embed a knowledge source (§6). Enqueued by the knowledge API.

    Bridges the API (stores source/upload) and the agent-core ingestion module
    (parses, chunks, embeds). Sets source.status ready/error accordingly.
    """

    bound = logger.bind(source_id=source_id, tenant_id=tenant_id)
    # The try is OUTSIDE the session, and that placement is the fix.
    #
    # An earlier attempt put it inside, which looked right and did nothing: the
    # NUL byte does not fail when the chunks are added, it fails when the
    # transaction is *committed*, and the commit happens as the `async with`
    # block exits, after any handler inside it has been passed. The live
    # symptom was a log line reading "ingested source: 1 chunks" immediately
    # followed by a DBAPIError, a source still marked pending_ingest, and an
    # owner watching a spinner for ever.
    #
    # Only reproducing it against a real Postgres showed that. A structural
    # test that the handler existed passed the whole time.
    try:
        await _ingest_source_inner(source_id, tenant_id, bound)
    except Exception as exc:  # noqa: BLE001 - a dead job must not look alive
        bound.error(f"ingest failed: {exc}")
        await _mark_source_failed(tenant_id, source_id, exc)
        raise


async def _ingest_source_inner(source_id: str, tenant_id: str, bound: Any) -> None:
    """The body, so a commit failure has somewhere to be caught."""
    from app.agent.ingestion import extract_text, fetch_url_text, ingest_source
    from app.api.knowledge_limits import check_room_for, source_chars
    from app.core.limits import LimitExceeded
    from app.models.knowledge import KnowledgeSource
    from app.models.tenant import TenantConfig
    from app.providers.registry import resolve_embedding

    async with tenant_session(UUID(tenant_id)) as db:
        source = (
            await db.execute(select(KnowledgeSource).where(KnowledgeSource.id == UUID(source_id)))
        ).scalar_one_or_none()
        if source is None:
            bound.warning("ingest: source not found")
            return
        # No try here: the caller owns broad handling, because a commit
        # failure happens as this block exits and cannot be caught from
        # inside it. Catching here as well would swallow the error the
        # caller needs in order to record the source as failed.
        if source.content:
            text = extract_text(source_type="text", raw_text=source.content)
        elif source.url:
            text = await fetch_url_text(source.url)
        else:
            upload_path = (source.meta or {}).get("upload_path")
            if not upload_path:
                raise ValueError("source has neither inline content nor an upload")
            raw = await anyio.Path(upload_path).read_bytes()
            text = extract_text(
                source_type=Path(upload_path).suffix or "text", raw_bytes=raw
            )
        # Re-check the plan's total before embedding anything (spec §2.3).
        # The API cannot do this alone: a URL source has no size at all
        # until it has been fetched, and a file that passed the per-file
        # check can still be the one that puts the tenant over. Embedding
        # is where the money is spent, so this is the last honest place to
        # stop, and it must happen before resolve_embedding is called.
        try:
            await check_room_for(
                db,
                UUID(tenant_id),
                added_chars=len(text),
                # The chunks about to be replaced. A re-ingest of the same
                # document must not be charged twice.
                replacing_chars=await source_chars(db, source.id),
            )
        except LimitExceeded as err:
            # A refused ingest is a visible error on the source rather than
            # a silent no-op: the owner uploaded something and is entitled
            # to know it is not being used.
            source.status = "error"
            source.meta = {**(source.meta or {}), "error": str(err)}
            bound.warning(f"ingest refused, over plan limit: {err}")
            return

        tenant_config = (
            await db.execute(
                select(TenantConfig).where(TenantConfig.tenant_id == UUID(tenant_id))
            )
        ).scalar_one_or_none()
        embedder = resolve_embedding(tenant_config)
        ingest_usage: dict[str, int] = {}
        chunks = await ingest_source(
            db, source, text=text, embedder=embedder, usage_out=ingest_usage
        )
        source.status = "ready"
        # Stamped on success only (teardown K2). A source whose last crawl
        # failed must keep the timestamp of the last one that worked, or
        # "last crawled 2 minutes ago" would describe a fetch that brought
        # back nothing.
        source.last_ingested_at = datetime.now(UTC)
        bound.info(f"ingested source: {len(chunks)} chunks")

        # Ingestion embeds every chunk, and that is billed. One-off per
        # source, but a large knowledge base is not a rounding error.
        embed_tokens = ingest_usage.get("embedding_tokens", 0)
        if embed_tokens:
            from app.providers.registry import resolve_embedding_identity
            from app.workers.pipeline import compute_cost, record_billed_usage

            emb_provider, emb_model = resolve_embedding_identity(tenant_config)
            await record_billed_usage(
                UUID(tenant_id),
                messages_in=0,
                messages_out=0,
                tokens=embed_tokens,
                cost=compute_cost(emb_provider, emb_model, embed_tokens, 0),
            )


async def _mark_source_failed(tenant_id: str, source_id: str, exc: Exception) -> None:
    """Record an ingestion failure on its own connection. Never raises.

    Its own connection because the caller's may be the casualty: a
    ``DBAPIError`` aborts the transaction, and every subsequent write on that
    session fails until it is rolled back. Writing the status there looked
    correct and silently did nothing, which is why a stuck source claimed to
    be in progress for ever.

    Never raises, because this is already the error path. If even this cannot
    write, the log line at the call site is the record, and re-raising would
    replace one lost failure with another.
    """
    from app.models.knowledge import KnowledgeSource

    try:
        async with tenant_session(UUID(tenant_id)) as db:
            source = (
                await db.execute(
                    select(KnowledgeSource).where(KnowledgeSource.id == UUID(source_id))
                )
            ).scalar_one_or_none()
            if source is None:
                return
            source.status = "error"
            # Reassigned, not mutated: JSONBType has no MutableDict, so an
            # in-place update is never flushed (CLAUDE.md records this).
            source.meta = {**(source.meta or {}), "error": _readable_ingest_error(exc)}
    except Exception as inner:  # noqa: BLE001 - see the docstring
        logger.error(f"could not mark source {source_id} failed: {inner}")


def _readable_ingest_error(exc: Exception) -> str:
    """One sentence an owner can act on, from an exception they cannot read."""
    text = str(exc)
    if "CharacterNotInRepertoireError" in text or "invalid byte sequence" in text:
        return (
            "This file contains characters we could not store. Try saving it again "
            "from the original application, or upload it as plain text."
        )
    if "LimitExceeded" in type(exc).__name__ or "limit" in text.lower():
        return text
    if "no readable text" in text.lower():
        return (
            "We could not find any readable text in this file. A scanned image "
            "needs to be a text PDF, not a picture of one."
        )
    if "timeout" in text.lower() or "timed out" in text.lower():
        return "This took too long to read. Try again, or upload a smaller file."
    # Truncated: the full exception is in the log, and an owner-facing field is
    # not the place for a stack trace.
    return f"We could not read this file. {text[:180]}"


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
    functions = [process_conversation, close_debounce_window, ingest_knowledge_source]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_tries = settings.job_max_retries
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
