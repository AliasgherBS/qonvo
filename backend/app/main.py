"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    account,
    activation,
    admin,
    auth,
    behavior_assist,
    billing,
    billing_webhooks,
    conversations,
    health,
    knowledge,
    notifications,
    onboarding,
    sessions,
    team,
    webhooks,
)
from app.api import analytics as analytics_api
from app.api import config as config_api
from app.api import integrations as integrations_api
from app.api import metrics as metrics_api
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.core.redis import close_redis
from app.core.validation import quiet_errors
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

@app.exception_handler(RequestValidationError)
async def _quiet_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """A 422 that reports the shape of the error, not the content (F10).

    App-wide, after starting out as a route class on the routers known to
    carry secrets. That was the wrong call and the reasoning is in
    ``app.core.validation``: pydantic sets ``input`` to the whole submitted
    body for a ``missing`` error, so *any* route with a required field can
    return every other field, and a curated list of routers only ever covers
    the ones somebody thought of. Four were found by asking the property of
    the route table; the fifth was found by tripping over it -- a mistyped
    field on ``POST /api/conversations/{id}/reply`` came back with the whole
    message a business was sending a customer.

    Making it global costs nothing: ``quiet_errors`` preserves the status code
    and the ``detail``-is-a-list shape, and the only client reads
    ``detail[0].msg`` (dashboard/lib/api.ts). Nothing anywhere reads ``input``
    or ``ctx``, which is what this drops.
    """
    return JSONResponse(
        # UNPROCESSABLE_CONTENT, not _ENTITY: this starlette deprecates the
        # older name and warns on every validation error, which would put a
        # deprecation warning in front of a real one on a live request.
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(quiet_errors(exc.errors()))},
    )


# Browser dashboard origins (env-driven; prod adds https://app.<domain>).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#: Headers every API response carries. Fewer than the dashboard needs, because
#: this host serves JSON to a known client rather than documents to a browser,
#: but the omissions were still real: a JSON endpoint with no `nosniff` can be
#: coerced into executing, and one with no `Referrer-Policy` leaks its own URL
#: onward. `api.qonvo.org` had none of these.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Nothing here is a document, so nothing here should ever be framed or
    # loaded as one.
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
}


@app.middleware("http")
async def _security_headers(request, call_next):
    """Attach the security headers to every response, including errors.

    Set here rather than in Caddy or the tunnel so they travel with the
    application: this API is reached through a Cloudflare Tunnel today and will
    be behind Caddy on a VPS later, and a header that lives in the proxy
    silently disappears when the proxy changes.
    """
    response = await call_next(request)
    for key, value in _SECURITY_HEADERS.items():
        # setdefault, not assignment: a route that deliberately set its own
        # (the docs UI needs a looser CSP) must win over the default.
        response.headers.setdefault(key, value)
    return response


@app.middleware("http")
async def _metrics_middleware(request, call_next):
    """Record per-route request counts + durations for GET /metrics (§12)."""
    if not settings.metrics_enabled:
        return await call_next(request)
    import time

    from app.core.metrics import record_request

    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    record_request(request.method, path, response.status_code, time.perf_counter() - start)
    return response


app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(sessions.router)

# --- Phase 1: platform API (auth, inbox, knowledge, config, notifications, ops) ---
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(knowledge.router)
app.include_router(config_api.router)
app.include_router(billing.router)
app.include_router(billing_webhooks.router)
app.include_router(notifications.router)
app.include_router(onboarding.router)
app.include_router(activation.router)
app.include_router(team.router)
app.include_router(account.router)
app.include_router(admin.router)
# The "Improve with AI" review on the Behavior page's custom instructions.
app.include_router(behavior_assist.router)

# --- Phase 3: agentic integrations (Google Calendar / Sheets) + analytics ---
app.include_router(integrations_api.router)
app.include_router(analytics_api.router)
app.include_router(metrics_api.router)
