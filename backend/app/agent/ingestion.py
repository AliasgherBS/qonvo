"""Knowledge ingestion — parse, chunk, embed, and store (DESIGN.md §6).

Supported inputs: plain text/markdown, CSV, PDF (``pypdf``), DOCX
(``python-docx``). PDF/DOCX parsers are imported lazily so this module stays
importable (and unit-testable) without those libraries installed.

Chunking targets ~500 tokens with 50 tokens of overlap, splitting on paragraph
boundaries first so a chunk never straddles a paragraph unless the paragraph
itself exceeds the target size. Token counts are approximated by word count
(no tokenizer dependency) — good enough for chunk sizing, not billing (billing
uses provider-reported token usage, see :mod:`app.workers.pipeline`).
"""

from __future__ import annotations

import csv
import io

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.knowledge import KnowledgeChunk, KnowledgeSource
from app.providers.base import EmbeddingProvider


async def fetch_url_text(url: str) -> str:
    """Fetch a web page and extract its readable text (URL knowledge sources).

    Strips script/style/nav/header/footer chrome and collapses whitespace so the
    chunker gets clean prose. Raises on a bad status or an empty page.
    """
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "QonvoBot/1.0 (+knowledge ingestion)"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    from lxml import html as lxml_html  # lazy — heavy import, only for URL sources

    doc = lxml_html.fromstring(resp.text)
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header|//form"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)
    lines = [ln.strip() for ln in doc.text_content().splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    if not cleaned.strip():
        raise ValueError("no readable text found at that URL")
    return cleaned


# --------------------------------------------------------------------------- #
# Parsers: raw bytes/text → plain text
# --------------------------------------------------------------------------- #
def parse_text(raw: str) -> str:
    """Plain text or markdown — passed through as-is."""
    return raw


def parse_csv(raw: str) -> str:
    """Render a CSV as one line per row, columns joined with ``: `` pairs when
    a header row is present, else comma-joined."""
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return ""
    header, *body = rows
    lines: list[str] = []
    for row in body:
        if len(header) == len(row):
            pairs = zip(header, row, strict=True)
            lines.append(", ".join(f"{h.strip()}: {v.strip()}" for h, v in pairs))
        else:
            lines.append(", ".join(row))
    return "\n".join(lines)


def parse_pdf(data: bytes) -> str:
    """Extract text from a PDF via ``pypdf`` (lazy import)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def parse_docx(data: bytes) -> str:
    """Extract text from a DOCX via ``python-docx`` (lazy import)."""
    import docx

    document = docx.Document(io.BytesIO(data))
    return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())


def extract_text(
    *, source_type: str, raw_text: str | None = None, raw_bytes: bytes | None = None
) -> str:
    """Dispatch to the right parser based on ``source_type`` (a file extension
    or a simple type tag: ``pdf``, ``docx``, ``csv``, ``text``/``markdown``)."""
    kind = source_type.lower().lstrip(".")
    if kind == "pdf":
        if raw_bytes is None:
            raise ValueError("PDF ingestion requires raw_bytes")
        return parse_pdf(raw_bytes)
    if kind in ("docx", "doc"):
        if raw_bytes is None:
            raise ValueError("DOCX ingestion requires raw_bytes")
        return parse_docx(raw_bytes)
    if kind == "csv":
        text = raw_text if raw_text is not None else (raw_bytes or b"").decode("utf-8", "ignore")
        return parse_csv(text)
    # text, markdown, md, or anything else falls back to plain text.
    text = raw_text if raw_text is not None else (raw_bytes or b"").decode("utf-8", "ignore")
    return parse_text(text)


# --------------------------------------------------------------------------- #
# Chunking (~500 tokens, 50 overlap, paragraph-respecting)
# --------------------------------------------------------------------------- #
def _word_count(text: str) -> int:
    return len(text.split())


def chunk_text(
    text: str,
    *,
    chunk_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[str]:
    """Split ``text`` into ~``chunk_tokens``-word chunks with word-based overlap.

    Paragraphs (blank-line separated) are packed greedily so a boundary is
    preferred over a mid-paragraph split; a paragraph longer than
    ``chunk_tokens`` is itself split on whitespace as a fallback.
    """
    chunk_tokens = chunk_tokens if chunk_tokens is not None else settings.rag_chunk_tokens
    overlap_tokens = (
        overlap_tokens if overlap_tokens is not None else settings.rag_chunk_overlap_tokens
    )

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    # Oversized paragraphs are pre-split into word-count-bounded pieces.
    units: list[str] = []
    for para in paragraphs:
        if _word_count(para) <= chunk_tokens:
            units.append(para)
            continue
        words = para.split()
        for i in range(0, len(words), chunk_tokens):
            units.append(" ".join(words[i : i + chunk_tokens]))

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in units:
        unit_words = _word_count(unit)
        if current and current_words + unit_words > chunk_tokens:
            chunks.append("\n\n".join(current))
            # Overlap: carry the tail words of the just-closed chunk forward.
            tail_words = "\n\n".join(current).split()[-overlap_tokens:] if overlap_tokens else []
            current = [" ".join(tail_words)] if tail_words else []
            current_words = len(tail_words)
        current.append(unit)
        current_words += unit_words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


# --------------------------------------------------------------------------- #
# Orchestration: chunk → embed → persist, tombstoning prior chunks
# --------------------------------------------------------------------------- #
async def ingest_source(
    db: AsyncSession,
    source: KnowledgeSource,
    *,
    text: str,
    embedder: EmbeddingProvider,
) -> list[KnowledgeChunk]:
    """Chunk + embed ``text`` for ``source``, tombstoning any prior chunks.

    Caller owns the transaction (commit/rollback) — this only stages ORM
    objects via ``db.add`` and an ``UPDATE`` for the tombstone.
    """
    await db.execute(
        update(KnowledgeChunk)
        .where(
            KnowledgeChunk.tenant_id == source.tenant_id,
            KnowledgeChunk.source_id == source.id,
            KnowledgeChunk.tombstoned.is_(False),
        )
        .values(tombstoned=True)
    )

    pieces = chunk_text(text)
    if not pieces:
        return []

    vectors = await embedder.embed(pieces)
    chunks: list[KnowledgeChunk] = []
    for piece, vector in zip(pieces, vectors, strict=True):
        chunk = KnowledgeChunk(
            tenant_id=source.tenant_id,
            source_id=source.id,
            content=piece,
            embedding=vector,
            token_count=_word_count(piece),
        )
        db.add(chunk)
        chunks.append(chunk)
    return chunks


async def ingest_raw(
    db: AsyncSession,
    source: KnowledgeSource,
    *,
    source_type: str,
    embedder: EmbeddingProvider,
    raw_text: str | None = None,
    raw_bytes: bytes | None = None,
) -> list[KnowledgeChunk]:
    """Parse raw input for ``source_type`` then delegate to :func:`ingest_source`."""
    text = extract_text(source_type=source_type, raw_text=raw_text, raw_bytes=raw_bytes)
    return await ingest_source(db, source, text=text, embedder=embedder)


__all__ = [
    "chunk_text",
    "extract_text",
    "ingest_raw",
    "ingest_source",
    "parse_csv",
    "parse_docx",
    "parse_pdf",
    "parse_text",
]
