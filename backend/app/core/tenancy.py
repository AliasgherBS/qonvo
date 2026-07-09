"""Tenant-scoped DB sessions that drive Postgres Row-Level Security.

Every tenant-scoped request runs inside a session that has issued
``SET LOCAL app.tenant_id = '<uuid>'``. RLS policies (see the initial migration)
compare each row's ``tenant_id`` against ``current_setting('app.tenant_id')`` so a
missing ``WHERE`` clause can never leak across tenants (DESIGN.md §3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory, system_session_factory


async def set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Bind ``app.tenant_id`` for the current transaction.

    ``SET LOCAL`` scopes the setting to the surrounding transaction, so it is
    reset automatically on commit/rollback — safe with pooled connections. The
    value is bound as a parameter to avoid any injection surface.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


@asynccontextmanager
async def tenant_session(tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Context-managed tenant-scoped session (for workers/scheduler)."""
    async with async_session_factory() as session, session.begin():
        await set_tenant(session, tenant_id)
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for trusted system paths (webhook tenant
    resolution, scheduler fleet scans).

    Connects as the dedicated ``qonvo_system`` role, which carries Postgres's
    native ``BYPASSRLS`` attribute. This is a *connection-level* privilege —
    unlike a GUC, it cannot be enabled from SQL by the app role, so a bug or
    injection in tenant-scoped code can never widen its own visibility.
    """
    async with system_session_factory() as session, session.begin():
        yield session


def tenant_session_dependency(tenant_id: UUID):
    """Build a FastAPI dependency yielding a tenant-scoped session.

    Wrap with the resolved tenant from the JWT, e.g.::

        async def route(session = Depends(...)): ...
    """

    async def _dep() -> AsyncIterator[AsyncSession]:
        async with tenant_session(tenant_id) as session:
            yield session

    return _dep
