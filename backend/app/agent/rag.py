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
    usage_out: dict[str, int] | None = None,
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

    # Embedding the query is a billed call on every inbound message. Report the
    # tokens so the pipeline can record them; providers that omit usage give 0.
    if hasattr(embedder, "embed_with_usage"):
        vectors, embed_usage = await embedder.embed_with_usage([query])
        if usage_out is not None:
            usage_out["embedding_tokens"] = embed_usage.prompt_tokens
    else:
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


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def build_context_block(chunks: list[RetrievedChunk], *, max_tokens: int | None = None) -> str:
    """Render retrieved chunks into a system-prompt context block.

    Chunks arrive best-first (by score). Overlapping ingestion produces
    near-identical neighbours, so exact-normalized duplicates are dropped, and
    the block is trimmed to ``max_tokens`` (~4 chars/token) so a big knowledge
    base can't inflate the grounding on every turn.
    """
    if not chunks:
        return ""
    max_tokens = max_tokens if max_tokens is not None else settings.rag_context_max_tokens
    budget_chars = max_tokens * 4

    parts: list[str] = []
    seen: set[str] = set()
    used_chars = 0
    idx = 0
    for chunk in chunks:
        key = _norm(chunk.content)
        if not key or key in seen:
            continue
        seen.add(key)
        idx += 1
        entry = f"[{idx}] {chunk.content}"
        # Always include the top chunk; stop once the budget is spent.
        if parts and used_chars + len(entry) > budget_chars:
            break
        parts.append(entry)
        used_chars += len(entry)
    return "\n\n".join(parts)


__all__ = ["RetrievedChunk", "build_context_block", "retrieve"]
