"""Who did what, in one place (teardown X8).

``audit_log`` was written by the admin console and by activation, and by
nothing else. Not when an integration was connected or disconnected, not when
knowledge was deleted, not when a team member was removed, not when the plan
was cancelled, not when config changed, and not when somebody took over a
conversation. In a product with staff seats those are exactly the actions worth
attributing.

**Both existing writers passed ``actor_user_id=None``**, so even the rows that
did exist recorded what happened and never who. That is the half that matters:
with one owner, "the plan was cancelled" is enough, because there is only one
candidate. With a receptionist on a staff seat it is not.

Failures here are swallowed. An audit row is a record of something that has
already happened, so a logging problem must not roll back the action it
describes -- and these are called inside the request's transaction, where a
raise would do exactly that. A missing row is bad; a cancelled subscription
that reports failure because its audit row would not write is worse.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.security import TokenClaims
from app.models.tenant import AuditLog, User

__all__ = ["changed_fields", "record"]


async def _actor_id(db: AsyncSession, email: str | None) -> UUID | None:
    """Resolve the acting user's id from the subject on their token.

    The token carries an email, not an id, and ``actor_user_id`` is a uuid
    column. One indexed lookup per audited action is the price of the row
    naming a person rather than nothing at all.
    """
    if not email:
        return None
    return (
        await db.execute(select(User.id).where(User.email == email))
    ).scalar_one_or_none()


async def record(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    claims: TokenClaims | None,
    action: str,
    target: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append one audit row. Never raises.

    ``action`` is a stable snake_case verb phrase, because these are queried by
    exact match and a reworded string is a silently broken query. The actor's
    email and role go into ``meta`` as well as the id: the id is a foreign key
    that says nothing on its own when somebody reads the table, and a removed
    member's row would otherwise become anonymous the moment the user is
    deleted.
    """
    try:
        subject = getattr(claims, "subject", None)
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=await _actor_id(db, subject),
                action=action,
                target=target,
                meta={
                    **({"actor_email": subject} if subject else {}),
                    **({"actor_role": claims.role} if claims and claims.role else {}),
                    # An impersonated session presents the customer's identity,
                    # so without this every row it writes reads as the customer
                    # having done it. The teardown's point exactly: the act of
                    # impersonating was logged and the actions were not.
                    **(
                        {"impersonated_by": claims.acting_as}
                        if getattr(claims, "acting_as", None)
                        else {}
                    ),
                    **(meta or {}),
                },
            )
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.warning(f"could not write audit row for {action}: {exc}")


def changed_fields(row: object, updates: dict[str, Any]) -> list[str]:
    """Which of ``updates`` actually differ from what is stored.

    Names only, never values. The most sensitive thing in the config is
    ``payment_details``, the text the rep reads out verbatim when a customer
    asks how to pay, and copying it into an audit row would duplicate it
    somewhere with a different retention story. Knowing *that* it changed and
    who changed it is what the record is for -- the current value is one query
    away for anybody entitled to it.
    """
    return sorted(
        field
        for field, value in updates.items()
        if hasattr(row, field) and getattr(row, field) != value
    )
