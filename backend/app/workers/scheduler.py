"""arq scheduler (cron jobs) — Phase 0 (DESIGN.md §12.1).

Currently runs the session-health poll every 60s. Reminder dispatch (§5.7) and
knowledge re-crawl (§6) plug in here in later phases.
"""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis import get_redis
from app.waha.client import WahaClient
from app.waha.send_gateway import SendGateway
from app.waha.session_health import poll_session_health


async def session_health_job(ctx: dict[str, Any]) -> None:
    waha: WahaClient = ctx["waha"]
    failed = await poll_session_health(waha)
    logger.bind(newly_failed=failed).info("session-health poll complete")


async def booking_reminders_job(ctx: dict[str, Any]) -> None:
    """Send due booking confirmations + 24h reminders (§5.7)."""
    if not settings.reminders_enabled:
        return
    from app.agent.reminders import dispatch_due_reminders

    stats = await dispatch_due_reminders(
        ctx["send_gateway"], lookahead_hours=settings.reminder_lookahead_hours
    )
    logger.bind(**stats).info("booking-reminders scan complete")


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    waha = WahaClient()
    ctx["waha"] = waha
    ctx["send_gateway"] = SendGateway(waha, get_redis())
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
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # CRITICAL: own queue. arq consumers compete for jobs on a shared queue —
    # without this, the scheduler steals worker jobs (e.g. ingest_knowledge_source)
    # and drops them as "function not found". Caught live.
    queue_name = "arq:scheduler"
