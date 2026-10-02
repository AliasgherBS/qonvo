"""Liveness/readiness endpoints (DESIGN.md §12.4, CAPACITY-AND-SCALING.md P4).

Three probes, because "is it up" and "can it do its job" are different
questions and conflating them is how an outage goes unnoticed.

``/healthz``      liveness. The process is running. Dependency-free.
``/readyz``       infrastructure. DB, Redis and the WAHA container reachable.
``/readyz/deep``  the product. Can this system actually answer a customer?

**Why the third one exists.** On 2026-09-09 a firewall rule blocked all
outbound TCP. WAHA could not reach WhatsApp, the LLM was unreachable, the bot
was completely silent -- and ``/readyz`` returned
``{"status":"ok","checks":{"database":"ok","redis":"ok","waha":"ok"}}`` the
whole time. ``waha: ok`` means the API can reach the WAHA *container*; it says
nothing about whether WAHA can reach WhatsApp. A readiness probe that cannot
tell healthy from totally non-functional is worse than none, because it will
be trusted.

**Why it is a separate route rather than more checks on ``/readyz``.** The
deploy workflow greps ``/readyz`` for ``"status":"ok"`` and rolls back when it
does not find it. A tenant whose number happens to be re-linking is not a
reason to roll back a release, so the product-level checks live here and the
deployment gate keeps the narrower contract it already had. Point uptime
monitoring at ``/readyz/deep``; point the deploy at ``/readyz``.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_system_db, get_waha
from app.core.config import settings
from app.core.logging import logger
from app.core.redis import get_redis
from app.models.whatsapp import WhatsAppSession
from app.waha.client import WahaClient

router = APIRouter(tags=["health"])

#: The deep checks reach outside the box, so they are cached. A probe that
#: becomes load is a probe that gets switched off.
_DEEP_TTL_SECONDS = 30
_deep_cache: tuple[float, dict[str, str]] | None = None


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness — the process is running. Deliberately dependency-free."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    response: Response,
    db: AsyncSession = Depends(get_system_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Readiness — every hard dependency is reachable. 503 if any is down."""
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — report, don't raise
        checks["database"] = f"fail: {type(exc).__name__}"

    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"fail: {type(exc).__name__}"

    checks["waha"] = "ok" if await waha.ping() else "fail: unreachable"

    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}


async def _llm_reachable() -> str:
    """Can we reach the configured LLM endpoint at all?

    Deliberately a connection check and not a completion: a readiness probe
    that spends money every thirty seconds is one nobody can afford to leave
    running. This answers "is the network path open", which is exactly the
    question the September outage needed answered and the one `waha: ok` could
    not.
    """
    base = (settings.llm_base_url or "").rstrip("/")
    if not base:
        return "skipped: no base url configured"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Any answer at all proves the path is open. A 401 from a models
            # listing is a perfectly healthy signal here -- it means we reached
            # the provider, which is all this check claims.
            response = await client.get(f"{base}/models")
        if response.status_code < 500:
            return "ok"
        return f"fail: provider returned {response.status_code}"
    except Exception as exc:  # noqa: BLE001 - the probe reports, never raises
        return f"fail: {type(exc).__name__}"


async def _whatsapp_working(db: AsyncSession) -> str:
    """Is any number actually linked and working?

    Across the fleet rather than per tenant: this probe answers "is the product
    able to reply to anyone", and a single tenant mid-rescan must not read as a
    platform outage.
    """
    try:
        total = (
            await db.execute(select(func.count()).select_from(WhatsAppSession))
        ).scalar_one()
        if not total:
            return "skipped: no sessions provisioned"
        working = (
            await db.execute(
                select(func.count())
                .select_from(WhatsAppSession)
                .where(func.lower(WhatsAppSession.status) == "working")
            )
        ).scalar_one()
        if working:
            return f"ok: {working} of {total} working"
        return f"fail: 0 of {total} sessions working"
    except Exception as exc:  # noqa: BLE001
        return f"fail: {type(exc).__name__}"


@router.get("/readyz/deep")
async def readyz_deep(
    response: Response,
    db: AsyncSession = Depends(get_system_db),
    waha: WahaClient = Depends(get_waha),
) -> dict:
    """Can this system actually answer a customer right now?

    503 when it cannot. This is the probe to alert on; ``/readyz`` is the one
    the deployment gate watches.
    """
    global _deep_cache

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

    checks["waha_container"] = "ok" if await waha.ping() else "fail: unreachable"

    cached = _deep_cache
    if cached is not None and (time.time() - cached[0]) < _DEEP_TTL_SECONDS:
        checks.update(cached[1])
    else:
        outward = {
            "llm": await _llm_reachable(),
            "whatsapp": await _whatsapp_working(db),
        }
        _deep_cache = (time.time(), outward)
        checks.update(outward)

    # "skipped" is not a failure: an environment with no sessions provisioned,
    # or no LLM base url, is not broken -- it is not finished. Saying so is more
    # useful than a green tick that means nothing was looked at.
    failed = [name for name, value in checks.items() if value.startswith("fail")]
    if failed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        logger.warning(f"deep readiness failing: {', '.join(failed)}")
    return {
        "status": "ok" if not failed else "degraded",
        "checks": checks,
        "failing": failed,
    }
