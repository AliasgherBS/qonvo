"""Knowledge sources and pgvector-backed chunks (DESIGN.md §6, §11)."""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin
from app.db.types import JSONBType
from app.models.enums import KnowledgeSourceType

# Default embedding dimensionality (OpenAI text-embedding-3-small). Configurable
# per deployment; the column is fixed-width so keep this stable per environment.
EMBEDDING_DIM = 1536


class KnowledgeSource(Base, TenantScopedMixin):
    __tablename__ = "knowledge_sources"

    type: Mapped[KnowledgeSourceType] = mapped_column(
        Enum(KnowledgeSourceType, name="knowledge_source_type"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Inline content for manual sources; file/url sources ingest asynchronously.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ingestion lifecycle: pending_ingest → ready (chunked/embedded) — see §6.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_ingest")
    auto_refresh: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)


class KnowledgeChunk(Base, TenantScopedMixin):
    __tablename__ = "knowledge_chunks"

    source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONBType, nullable=False, default=dict)
    # Tombstone stale chunks on re-crawl instead of hard-deleting (DESIGN.md §6).
    tombstoned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
