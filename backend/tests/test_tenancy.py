"""Tenancy SET variable for RLS (DESIGN.md §3)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from app.core.tenancy import set_tenant


async def test_set_tenant_binds_app_tenant_id():
    session = AsyncMock()
    tenant_id = uuid4()

    await set_tenant(session, tenant_id)

    session.execute.assert_awaited_once()
    clause, params = session.execute.await_args.args
    sql = str(clause)
    assert "set_config" in sql
    assert "app.tenant_id" in sql
    # Bound as a parameter (not interpolated) and scoped to the transaction (true).
    assert params == {"tid": str(tenant_id)}
    assert ", true)" in sql
