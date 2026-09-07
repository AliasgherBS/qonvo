"""Re-encrypt stored credentials under a new Fernet key.

Run by ``scripts/rotate-secrets.sh`` with ``OLD_KEY`` and ``NEW_KEY`` in the
environment, inside the API container, so neither key is ever written to disk.

The reason this exists rather than the rotation simply swapping the key:
``integrations.encrypted_credentials`` holds every tenant's Google refresh
token. Change the key without migrating the ciphertext and the tokens become
undecryptable, which does not fail loudly. It fails the next time a booking
skill tries to reach Calendar, for a tenant who has no idea their integration
is gone, and the only recovery is asking each owner to reconnect.

Idempotent and safe to re-run: a row that already decrypts under the new key is
left alone.
"""

from __future__ import annotations

import asyncio
import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update

from app.core.tenancy import system_session
from app.models.skill import Integration


async def main() -> int:
    old_key = os.environ.get("OLD_KEY", "").strip()
    new_key = os.environ.get("NEW_KEY", "").strip()
    if not old_key or not new_key:
        print("OLD_KEY and NEW_KEY are both required", file=sys.stderr)
        return 2
    if old_key == new_key:
        print("OLD_KEY and NEW_KEY are the same; nothing to do")
        return 0

    old = Fernet(old_key.encode())
    new = Fernet(new_key.encode())

    # system_session, not tenant_session: this walks every tenant's rows, which
    # is exactly what the BYPASSRLS role exists for.
    async with system_session() as db:
        rows = (
            (
                await db.execute(
                    select(Integration.id, Integration.encrypted_credentials).where(
                        Integration.encrypted_credentials.isnot(None),
                        Integration.encrypted_credentials != "",
                    )
                )
            )
            .all()
        )

        migrated = already = failed = 0
        for row_id, ciphertext in rows:
            try:
                plaintext = old.decrypt(ciphertext.encode())
            except InvalidToken:
                # Either already under the new key (a re-run) or encrypted under
                # a key we no longer hold. Distinguishing the two matters: the
                # first is fine, the second must not be reported as success.
                try:
                    new.decrypt(ciphertext.encode())
                    already += 1
                except InvalidToken:
                    failed += 1
                    print(f"  ! {row_id} decrypts under neither key, left untouched")
                continue

            await db.execute(
                update(Integration)
                .where(Integration.id == row_id)
                .values(encrypted_credentials=new.encrypt(plaintext).decode())
            )
            migrated += 1

        # One transaction. A partial re-encryption would leave some rows on the
        # old key and some on the new, and neither key would then read them all.
        await db.commit()

    print(f"  re-encrypted {migrated}, already current {already}, unreadable {failed}")
    # A row nobody can decrypt is a real problem, but not a reason to abort a
    # rotation that has already migrated the rest: the alternative is leaving
    # the old key in place, which is the thing being fixed.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
