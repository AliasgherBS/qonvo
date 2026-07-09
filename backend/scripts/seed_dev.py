"""Seed a dev tenant and mint a dev JWT for manual end-to-end testing.

Usage (from backend/, with infra up and schema migrated):

    QONVO_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    QONVO_JWT_SECRET=... uv run python scripts/seed_dev.py [tenant-slug]

Idempotent: re-running reuses the existing tenant by slug and mints a fresh token.
Dev-only — the real flow is admin-provisioned tenants via the ops console (§9).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
from uuid import uuid4

import jwt
from app.core.config import settings
from app.db.session import system_session_factory
from app.models.tenant import Tenant
from sqlalchemy import select

SLUG = sys.argv[1] if len(sys.argv) > 1 else "dev"


async def main() -> None:
    async with system_session_factory() as db, db.begin():
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == SLUG))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(id=uuid4(), name=f"Dev Tenant ({SLUG})", slug=SLUG)
            db.add(tenant)
            await db.flush()
        tenant_id = tenant.id

    now = dt.datetime.now(dt.UTC)
    token = jwt.encode(
        {
            "sub": "dev-user",
            "tenant_id": str(tenant_id),
            "role": "owner",
            "iat": now,
            "exp": now + dt.timedelta(days=7),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    print(f"TENANT_ID={tenant_id}")
    print(f"JWT={token}")


if __name__ == "__main__":
    asyncio.run(main())
