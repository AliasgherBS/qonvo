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
#: A 10 MB PDF is already thousands of chunks. This is also the guard that
#: stops one request holding a large file in memory in the API process.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: One pasted text entry, roughly twenty pages.
MAX_TEXT_ENTRY_CHARS = 50_000

#: Entitlement keys, so plans.py owns the per-plan figures.
KNOWLEDGE_SOURCES_KEY = "knowledge_sources"
KNOWLEDGE_CHARS_KEY = "knowledge_chars"


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
