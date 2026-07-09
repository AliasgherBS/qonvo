"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from app.api import health, sessions, webhooks
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis import close_redis
from app.waha.client import WahaClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.waha = WahaClient()
    logger.info("api started", environment=settings.environment)
    try:
        yield
    finally:
        await app.state.waha.aclose()
        await app.state.arq.aclose()
        await close_redis()
        logger.info("api stopped")


app = FastAPI(
    title="Qonvo API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(sessions.router)
