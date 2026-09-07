"""Per-tenant knowledge quota checks (spec §2).

Kept out of ``api/knowledge.py`` because the ingestion worker needs the same
answers and must not import a FastAPI router to get them. The worker has to
re-check, not trust the API: a file passes the per-file size check on its own
and can still push the tenant over its total, and a URL source has no size at
all until it has been fetched.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limits import (
    KNOWLEDGE_CHARS_KEY,
    KNOWLEDGE_SOURCES_KEY,
    KNOWLEDGE_UPLOAD_BYTES_KEY,
    LimitExceeded,
    entitlement,
    exceeded,
)
from app.models.knowledge import KnowledgeSource
from app.models.tenant import TenantConfig

__all__ = ["KnowledgeUsage", "check_room_for", "usage_for"]

#: Fallbacks for a tenant whose entitlements predate these keys. The trial
#: figures, so a missing entitlement is restrictive-but-usable rather than
#: unlimited: an unbounded default would make the cap silently optional for
#: exactly the tenants nobody has looked at.
DEFAULT_MAX_SOURCES = 50
DEFAULT_MAX_CHARS = 2_000_000
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class KnowledgeUsage:
    """What a tenant has used and what it is allowed."""

    __slots__ = (
        "chars",
        "max_chars",
        "max_sources",
        "max_upload_bytes",
        "sources",
        "upload_bytes",
    )

    def __init__(
        self,
        *,
        sources: int,
        chars: int,
        max_sources: int,
        max_chars: int,
        upload_bytes: int = 0,
        max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    ) -> None:
        self.sources = sources
        self.chars = chars
        self.max_sources = max_sources
        self.max_chars = max_chars
        self.upload_bytes = upload_bytes
        self.max_upload_bytes = max_upload_bytes

    @property
    def sources_remaining(self) -> int:
        return max(0, self.max_sources - self.sources)

    @property
    def chars_remaining(self) -> int:
        return max(0, self.max_chars - self.chars)

    @property
    def upload_bytes_remaining(self) -> int:
        return max(0, self.max_upload_bytes - self.upload_bytes)

    def as_dict(self) -> dict[str, int]:
        return {
            "sources": self.sources,
            "max_sources": self.max_sources,
            "chars": self.chars,
            "max_chars": self.max_chars,
            "upload_bytes": self.upload_bytes,
            "max_upload_bytes": self.max_upload_bytes,
        }


async def usage_for(db: AsyncSession, tenant_id: uuid.UUID) -> KnowledgeUsage:
    """Count what this tenant currently holds, against what its plan allows.

    Characters are summed from stored content. A source still being fetched
    contributes nothing yet, which is why the worker re-checks after it has the
    text rather than relying on this number alone.
    """
    counted = (
        await db.execute(
            select(
                func.count(KnowledgeSource.id),
                func.coalesce(func.sum(func.length(func.coalesce(KnowledgeSource.content, ""))), 0),
                # Upload size is written into meta at upload time rather than
                # stat()-ing the volume: the API and the worker are different
                # containers, and a number that depends on which one is asking
                # is not a quota.
                func.coalesce(
                    func.sum(
                        func.coalesce(
                            KnowledgeSource.meta["upload_bytes"].astext.cast(BigInteger), 0
                        )
                    ),
                    0,
                ),
            ).where(KnowledgeSource.tenant_id == tenant_id)
        )
    ).one()

    entitlements = (
        await db.execute(
            select(TenantConfig.entitlements).where(TenantConfig.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()

    return KnowledgeUsage(
        sources=int(counted[0] or 0),
        chars=int(counted[1] or 0),
        upload_bytes=int(counted[2] or 0),
        max_sources=entitlement(entitlements, KNOWLEDGE_SOURCES_KEY, DEFAULT_MAX_SOURCES),
        max_chars=entitlement(entitlements, KNOWLEDGE_CHARS_KEY, DEFAULT_MAX_CHARS),
        max_upload_bytes=entitlement(
            entitlements, KNOWLEDGE_UPLOAD_BYTES_KEY, DEFAULT_MAX_UPLOAD_BYTES
        ),
    )


async def check_room_for(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    new_source: bool = False,
    added_chars: int = 0,
    replacing_chars: int = 0,
    added_bytes: int = 0,
) -> KnowledgeUsage:
    """Raise ``LimitExceeded`` if this write would put the tenant over.

    ``replacing_chars`` is what the write removes, so editing a source down in
    size is never refused for being over a total the edit itself reduces. Only
    the delta is charged.
    """
    usage = await usage_for(db, tenant_id)

    if new_source and usage.sources >= usage.max_sources:
        raise exceeded(
            "Knowledge sources",
            limit=usage.max_sources,
            actual=usage.sources + 1,
            unit="sources",
        )

    delta = added_chars - replacing_chars
    if delta > 0 and usage.chars + delta > usage.max_chars:
        raise exceeded(
            "Total knowledge",
            limit=usage.max_chars,
            actual=usage.chars + delta,
        )

    if added_bytes > 0 and usage.upload_bytes + added_bytes > usage.max_upload_bytes:
        raise exceeded(
            "Uploaded files",
            limit=usage.max_upload_bytes // (1024 * 1024),
            actual=(usage.upload_bytes + added_bytes + 1024 * 1024 - 1) // (1024 * 1024),
            unit="MB",
        )
    return usage


def as_http_detail(err: LimitExceeded) -> str:
    """The message, plus the one thing the owner can do about it."""
    return f"{err}. Delete something you no longer need, or move to a larger plan."
