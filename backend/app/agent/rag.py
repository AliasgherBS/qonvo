"""RAG retrieval — tenant-scoped pgvector cosine search (DESIGN.md §6).

Embeds the query, then runs a single tenant-scoped SQL statement (never a
post-filter — DESIGN.md §3) that excludes tombstoned chunks and orders by
cosine distance. Below ``min_score`` the caller sees an empty result, which is
what forces the grounded pipeline into "I don't know" / handoff behavior.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import KnowledgeChunk
from app.providers.base import EmbeddingProvider


@dataclass(slots=True)
class RetrievedChunk:
    id: uuid.UUID
    source_id: uuid.UUID
    content: str
    score: float


async def retrieve(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    query: str,
    *,
    embedder: EmbeddingProvider,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[RetrievedChunk]:
    """Embed ``query`` and return the top-k tenant-scoped chunks above threshold.

    Cosine distance (``<=>``) ranges 0 (identical) .. 2 (opposite); similarity
    score is ``1 - distance``. Chunks scoring below ``min_score`` are dropped —
    an empty result here means "nothing relevant", by design.
    """
    top_k = top_k if top_k is not None else settings.rag_top_k
    min_score = min_score if min_score is not None else settings.rag_min_score

    if not query or not query.strip():
        return []

    vectors = await embedder.embed([query])
    if not vectors:
        return []
    query_vector = vectors[0]

    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(KnowledgeChunk, distance.label("distance"))
        .where(
            KnowledgeChunk.tenant_id == tenant_id,
            KnowledgeChunk.tombstoned.is_(False),
            KnowledgeChunk.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()

    results: list[RetrievedChunk] = []
    for chunk, dist in rows:
        score = 1.0 - float(dist)
        if score < min_score:
            continue
        results.append(
            RetrievedChunk(
                id=chunk.id,
                source_id=chunk.source_id,
                content=chunk.content,
                score=score,
            )
        )
    return results


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks into a system-prompt context block."""
    if not chunks:
        return ""
    parts = [f"[{i + 1}] {chunk.content}" for i, chunk in enumerate(chunks)]
    return "\n\n".join(parts)


__all__ = ["RetrievedChunk", "build_context_block", "retrieve"]
