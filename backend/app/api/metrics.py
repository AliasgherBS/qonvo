"""GET /metrics — Prometheus text exposition (DESIGN.md §12)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.core import obs
from app.core.config import settings
from app.core.metrics import render_prometheus

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    # In-process HTTP metrics (this API process) + shared business/pipeline metrics
    # that the worker also writes to Redis — one scrape target covers everything.
    return render_prometheus() + await obs.render()


__all__ = ["router"]
