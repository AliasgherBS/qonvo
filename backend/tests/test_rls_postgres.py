"""RLS cross-tenant isolation — requires a live, MIGRATED Postgres (DESIGN.md §3, §17).

Runs against the real schema created by ``alembic upgrade head`` — never
``metadata.create_all``, which would silently drop the RLS policies and test
nothing. Two connections are required:

- ``QONVO_TEST_DATABASE_URL``        — the NON-superuser app role (assertions).
- ``QONVO_TEST_SYSTEM_DATABASE_URL`` — the BYPASSRLS system role (seeding/cleanup).

Skipped unless both are set. Example:

    QONVO_TEST_DATABASE_URL=postgresql+asyncpg://qonvo_app:...@localhost:5433/qonvo \\
    QONVO_TEST_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    uv run pytest -m postgres
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.postgres

_APP_URL = os.environ.get("QONVO_TEST_DATABASE_URL")
_SYSTEM_URL = os.environ.get("QONVO_TEST_SYSTEM_DATABASE_URL")

if _APP_URL is None or _SYSTEM_URL is None:
    pytest.skip(
        "QONVO_TEST_DATABASE_URL / QONVO_TEST_SYSTEM_DATABASE_URL not set",
        allow_module_level=True,
    )


@pytest.fixture
async def engines():
    app_eng = create_async_engine(_APP_URL, poolclass=None)
    sys_eng = create_async_engine(_SYSTEM_URL, poolclass=None)
    yield app_eng, sys_eng
    await app_eng.dispose()
    await sys_eng.dispose()


async def test_app_role_is_not_superuser(engines):
    """Guard: assertions below are meaningless if the app role bypasses RLS."""
    app_eng, _ = engines
    async with app_eng.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).scalar_one()
        assert row is False, "app role must be NOSUPERUSER + NOBYPASSRLS"


async def test_rls_blocks_cross_tenant(engines):
    from app.core.tenancy import set_tenant
    from app.models.tenant import Tenant

    app_eng, sys_eng = engines
    tenant_a, tenant_b = uuid4(), uuid4()
    app_maker = async_sessionmaker(app_eng, expire_on_commit=False)
    sys_maker = async_sessionmaker(sys_eng, expire_on_commit=False)

    # Seed two tenants as the BYPASSRLS system role.
    async with sys_maker() as s, s.begin():
        s.add_all(
            [
                Tenant(id=tenant_a, name="RLS-Test-A", slug=f"rls-a-{tenant_a.hex[:8]}"),
                Tenant(id=tenant_b, name="RLS-Test-B", slug=f"rls-b-{tenant_b.hex[:8]}"),
            ]
        )

    try:
        # Scoped to tenant A: only tenant A visible, even with no app-layer filter.
        async with app_maker() as s, s.begin():
            await set_tenant(s, tenant_a)
            rows = (await s.execute(select(Tenant))).scalars().all()
            assert [r.id for r in rows] == [tenant_a]

        # No tenant bound at all → zero rows, not everything.
        async with app_maker() as s, s.begin():
            rows = (await s.execute(select(Tenant))).scalars().all()
            assert rows == []

        # WITH CHECK: writing a row for another tenant while scoped to A fails.
        async with app_maker() as s:
            await s.begin()
            await set_tenant(s, tenant_a)
            s.add(Tenant(id=uuid4(), name="evil", slug=f"evil-{uuid4().hex[:8]}"))
            with pytest.raises(Exception, match="row-level security|RowSecurityError"):
                await s.commit()
    finally:
        async with sys_maker() as s, s.begin():
            await s.execute(delete(Tenant).where(Tenant.id.in_([tenant_a, tenant_b])))
