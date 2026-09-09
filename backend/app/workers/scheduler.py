"""arq scheduler (cron jobs) — Phase 0 (DESIGN.md §12.1).

Currently runs the session-health poll every 60s, which now also tells the
owner when their number stops replying. Knowledge re-crawl (§6) plugs in here
in a later phase.
"""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis import get_redis
from app.services.notifications import sweep_session_alerts
from app.waha.client import WahaClient
from app.waha.send_gateway import SendGateway
from app.waha.session_health import poll_session_health


async def session_health_job(ctx: dict[str, Any]) -> None:
    waha: WahaClient = ctx["waha"]
    failed = await poll_session_health(waha)
    logger.bind(gave_up=failed).info("session-health poll complete")

    # Detecting an outage and telling nobody about it is what F4 was: a real
    # tenant's number sat at FAILED for days, reported accurately on Fleet
    # Health and nowhere else. The poll writes the status; this turns a status
    # into an owner who knows. Separate from the poll on purpose, so a WAHA
    # error that aborts the poll cannot also silence the alerting, and so the
    # alert covers the states auto-recovery deliberately never touches
    # (SCAN_QR_CODE, STOPPED, and FAILED with no credentials to restart into).
    try:
        alerts = await sweep_session_alerts(
            ctx["redis"], send_gateway=ctx["send_gateway"]
        )
    except Exception as exc:  # noqa: BLE001 — the cron must survive to run again
        logger.warning(f"session-alert sweep failed: {exc}")
    else:
        if any(alerts.values()):
            logger.bind(**alerts).info("session-alert sweep complete")


async def booking_reminders_job(ctx: dict[str, Any]) -> None:
    """Send due booking confirmations + 24h reminders (§5.7)."""
    if not settings.reminders_enabled:
        return
    from app.agent.reminders import dispatch_due_reminders

    stats = await dispatch_due_reminders(
        ctx["send_gateway"], lookahead_hours=settings.reminder_lookahead_hours
    )
    logger.bind(**stats).info("booking-reminders scan complete")


async def warmup_advance_job(_ctx: dict[str, Any]) -> None:
    """Move new numbers through the warm-up schedule (§5.6)."""
    from app.waha.session_warmup import advance_warmup_stages

    moved = await advance_warmup_stages()
    if moved:
        logger.bind(**moved).info("warm-up stages advanced")


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    waha = WahaClient()
    ctx["waha"] = waha
    redis = get_redis()
    ctx["redis"] = redis
    ctx["send_gateway"] = SendGateway(waha, redis)
    logger.info("scheduler started")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    waha: WahaClient | None = ctx.get("waha")
    if waha is not None:
        await waha.aclose()
    logger.info("scheduler stopped")


class SchedulerSettings:
    # Poll at second 0 of every minute (= every 60s); also once at startup.
    cron_jobs = [
        cron(session_health_job, second=0, run_at_startup=True),
        # Booking reminders (§5.7): scan every 15 min + once at startup.
        cron(booking_reminders_job, minute={0, 15, 30, 45}, run_at_startup=True),
        # Warm-up (§5.6) moves in whole days, so once a day is enough. Also at
        # startup, so a box that was off over a stage boundary catches up.
        cron(warmup_advance_job, hour=3, minute=0, run_at_startup=True),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # CRITICAL: own queue. arq consumers compete for jobs on a shared queue —
    # without this, the scheduler steals worker jobs (e.g. ingest_knowledge_source)
    # and drops them as "function not found". Caught live.
    queue_name = "arq:scheduler"
