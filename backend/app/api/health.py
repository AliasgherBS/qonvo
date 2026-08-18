"""Liveness/readiness endpoints (DESIGN.md §12.4).

``/healthz`` = liveness (is the process up). ``/readyz`` = readiness (can it
actually serve — DB, Redis, and WAHA reachable). Uptime monitors and the metrics
stack watch ``/readyz`` so a process that's up but cut off from its datastores is
reported unhealthy instead of silently failing every request.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_system_db, get_waha
from app.core.redis import get_redis
from app.waha.client import WahaClient

router = APIRouter(tags=["health"])


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
