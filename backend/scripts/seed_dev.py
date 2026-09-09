"""Seed a dev tenant + owner user and mint a dev JWT for manual end-to-end testing.

Usage (from backend/, with infra up and schema migrated):

    QONVO_SYSTEM_DATABASE_URL=postgresql+asyncpg://qonvo_system:...@localhost:5433/qonvo \\
    QONVO_JWT_SECRET=... uv run python scripts/seed_dev.py [tenant-slug]

Idempotent: re-running reuses the existing tenant/user by slug/email and mints a
fresh token. Also creates an owner user (Phase 1 login, DESIGN.md §8) with a
known dev password and a default ``tenant_config`` row, so ``POST
/api/auth/login`` works against the seeded tenant without going through the ops
console. Dev-only — the real flow is admin-provisioned tenants (§9).
"""

from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

from app.core.security import decode_jwt
from app.db.session import system_session_factory
from app.models.enums import UserRole
from app.models.tenant import Tenant, TenantConfig, TenantUser, User
from app.services.auth import create_access_token, hash_password
from sqlalchemy import select

SLUG = sys.argv[1] if len(sys.argv) > 1 else "dev"
DEV_OWNER_EMAIL = f"owner@{SLUG}.dev"
DEV_OWNER_PASSWORD = "dev-password-123"


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

        config = (
            await db.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if config is None:
            db.add(TenantConfig(tenant_id=tenant_id))

        user = (
            await db.execute(select(User).where(User.email == DEV_OWNER_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=DEV_OWNER_EMAIL,
                hashed_password=hash_password(DEV_OWNER_PASSWORD),
                full_name="Dev Owner",
            )
            db.add(user)
            await db.flush()

            db.add(TenantUser(tenant_id=tenant_id, user_id=user.id, role=UserRole.owner))

        # Qonvo staff superadmin (cross-tenant). Not tied to this tenant —
        # the impersonation flow (§9) is how they see any given tenant.
        admin = (
            await db.execute(select(User).where(User.email == "admin@qonvo.dev"))
        ).scalar_one_or_none()
        if admin is None:
            db.add(
                User(
                    email="admin@qonvo.dev",
                    hashed_password=hash_password("dev-admin-123"),
                    full_name="Qonvo Admin",
                    is_qonvo_admin=True,
                )
            )

    # Minted through create_access_token, not beside it. Two hand-rolled
    # copies of that payload have drifted from it already: this script missed
    # `typ` when it became required and 401'd every seeded token, and it missed
    # `jti` so the token could not be revoked -- logout returned 204 and the
    # token kept working. A week's TTL so a dev token survives a session.
    token = create_access_token(
        subject=DEV_OWNER_EMAIL,
        tenant_id=tenant_id,
        role="owner",
        is_qonvo_admin=False,
        expires_in_hours=24 * 7,
    )
    # Prove it before printing it. A seed script that prints an unusable token
    # wastes somebody's afternoon before they think to doubt the token.
    claims = decode_jwt(token)
    assert claims.jti, "a seeded token must be revocable"

    print(f"TENANT_ID={tenant_id}")
    print(f"OWNER_EMAIL={DEV_OWNER_EMAIL}")
    print(f"OWNER_PASSWORD={DEV_OWNER_PASSWORD}")
    print(f"JWT={token}")


if __name__ == "__main__":
    asyncio.run(main())
