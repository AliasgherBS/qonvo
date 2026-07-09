"""Dashboard notification log (DESIGN.md §5.5, §10, §12.1)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_tenant
from app.models.ops import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _to_dict(row: Notification) -> dict:
    return {
        "id": str(row.id),
        "type": row.type.value,
        "title": row.title,
        "body": row.body,
        "read": row.read,
        "meta": row.meta,
        "created_at": row.created_at,
    }


@router.get("")
async def list_notifications(
    unread: bool | None = Query(default=None),
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    filters = [Notification.tenant_id == tenant_id]
    if unread is not None:
        filters.append(Notification.read == (not unread))
    rows = (
        await db.execute(
            select(Notification).where(*filters).order_by(Notification.created_at.desc())
        )
    ).scalars().all()
    return [_to_dict(r) for r in rows]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: UUID,
    tenant_id: UUID = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification not found")
    row.read = True
    await db.flush()
    return _to_dict(row)


__all__ = ["router"]
