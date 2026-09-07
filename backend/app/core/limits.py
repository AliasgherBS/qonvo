"""Caps on what a tenant can put into the system (spec §2).

Two different problems live here, and they fail differently.

**Prompt fields** are paid for on every single turn. ``custom_instructions``
sits in the system prompt of every reply, so 50,000 characters pasted once is
~12,500 tokens billed forever, and worse answers with it: the real instructions
drown in the noise. The cap is small because the field is small by nature.

**Knowledge** is paid for at ingestion and stored forever. Every chunk is an
embedding row in pgvector and is re-embedded on re-crawl, so total characters
per tenant is the number that actually bounds storage spend. It scales by plan;
the prompt caps do not, because no plan makes a 50,000-character instruction a
good idea.

Adjusting a number here is a one-line change and needs no migration. The
per-plan figures live in the plan catalogue with the other entitlements, so a
plan change cannot leave a stale cap behind.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "KNOWLEDGE_CHARS_KEY",
    "KNOWLEDGE_SOURCES_KEY",
    "KNOWLEDGE_UPLOAD_BYTES_KEY",
    "MAX_CUSTOM_INSTRUCTIONS",
    "MAX_PAYMENT_DETAILS",
    "MAX_PERSONA",
    "MAX_TEXT_ENTRY_CHARS",
    "MAX_UPLOAD_BYTES",
    "LimitExceeded",
    "entitlement",
    "exceeded",
]

# --- Prompt fields, charged on every turn ---------------------------------- #
#: ~500 tokens on every reply. Twice what a well-written instruction set needs:
#: the live Depilex tenant runs 1,821 characters and reads as thorough.
MAX_CUSTOM_INSTRUCTIONS = 2_000

#: The persona dropdown covers most cases; this is the free-text escape hatch,
#: and a persona is a description rather than a document.
MAX_PERSONA = 500

#: Sent verbatim to customers, so length is a customer-experience limit as much
#: as a cost one. Nobody reads a 5,000-character payment instruction on WhatsApp.
MAX_PAYMENT_DETAILS = 1_000

# --- Knowledge, charged at ingestion and stored ---------------------------- #
#: Deliberately conservative, and not for the reason the other caps are.
#: A large document does not cost more to *answer* from, because retrieval only
#: ever puts the relevant chunks in the prompt. What it does is block the
#: ingestion queue: parsing and embedding a huge PDF is slow, single-threaded
#: per source, and every other tenant's upload waits behind it. Five megabytes
#: is already several hundred pages of text.
#:
#: It is also the bound on what one request holds in memory in the API process.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: One pasted text entry, roughly twenty pages.
MAX_TEXT_ENTRY_CHARS = 50_000

#: Entitlement keys, so plans.py owns the per-plan figures.
#:
#: Three separate bounds, because they constrain three different resources and
#: conflating them would price one of them wrongly:
#:
#: * ``knowledge_sources`` bounds the ingestion queue.
#: * ``knowledge_chars`` bounds pgvector. Generous on purpose: retrieval means
#:   only the relevant chunks reach a prompt, so a large corpus costs storage
#:   and a one-off embedding, never a bigger bill per reply.
#: * ``knowledge_upload_bytes`` bounds the disk volume. Raw uploads are kept
#:   after ingestion, so the file and its chunks are both stored. Keeping the
#:   original is what makes re-ingestion possible when chunking or the embedding
#:   model changes, and this is the cap that stops that being unbounded.
KNOWLEDGE_SOURCES_KEY = "knowledge_sources"
KNOWLEDGE_CHARS_KEY = "knowledge_chars"
KNOWLEDGE_UPLOAD_BYTES_KEY = "knowledge_upload_bytes"


class LimitExceeded(ValueError):
    """A limit was hit. Carries the numbers so callers can say which one."""

    def __init__(self, message: str, *, limit: int, actual: int) -> None:
        super().__init__(message)
        self.limit = limit
        self.actual = actual


def exceeded(what: str, *, limit: int, actual: int, unit: str = "characters") -> LimitExceeded:
    """Build the error message this codebase uses for every cap.

    It always names the limit **and the current value**. "Too long" makes
    someone binary-search their own paragraph; "limited to 2,000 characters,
    this is 3,140" tells them to cut 1,140 and be done.
    """
    return LimitExceeded(
        f"{what} is limited to {limit:,} {unit}. This is {actual:,}.",
        limit=limit,
        actual=actual,
    )


def entitlement(entitlements: dict[str, Any] | None, key: str, default: int) -> int:
    """Read a numeric entitlement, tolerating a tenant provisioned before it existed.

    Returning the default rather than raising is deliberate. These keys are new,
    so every tenant that predates them has no value, and a missing cap must not
    turn into a refused upload for someone who did nothing wrong.
    """
    if not entitlements:
        return default
    raw = entitlements.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
