"""Async engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    future=True,
    # Sized explicitly (CAPACITY-AND-SCALING.md P2). SQLAlchemy's defaults gave
    # every process 5+10, which across api, worker and scheduler is 90 possible
    # connections against max_connections=100 -- and the failure mode when it
    # tips over is a burst of TooManyConnections, not a slowdown.
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_timeout=settings.db_pool_timeout_seconds,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)

# Separate engine for the BYPASSRLS system role (webhook tenant resolution,
# scheduler fleet scans). Falls back to the app engine in dev if unset — RLS
# will then hide cross-tenant rows, which fails loudly rather than leaking.
system_engine: AsyncEngine = (
    create_async_engine(
        settings.system_database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        future=True,
        # Deliberately small: this engine serves a handful of trusted
        # cross-tenant lookups, so it must never be the reason the box runs out
        # of connections for ordinary requests.
        pool_size=settings.db_system_pool_size,
        max_overflow=settings.db_system_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_timeout=settings.db_pool_timeout_seconds,
    )
    if settings.system_database_url
    else engine
)

system_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=system_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Plain (non-tenant-scoped) session — for auth/webhook resolution only.

    Tenant-scoped request handlers must use :func:`app.core.tenancy.get_tenant_session`
    so RLS is enforced.
    """
    async with async_session_factory() as session:
        yield session
