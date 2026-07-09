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
