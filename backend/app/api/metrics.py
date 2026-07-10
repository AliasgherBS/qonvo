"""GET /metrics — Prometheus text exposition (DESIGN.md §12)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.metrics import render_prometheus

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    return render_prometheus()


__all__ = ["router"]
