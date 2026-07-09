"""Agent pipeline — Phase 0 stub (DESIGN.md §5.4).

This is an echo-style responder with the seams where STT / RAG / LLM / TTS plug
in later. The interfaces (``app.providers.base``) are stable; only the concrete
adapters and retrieval/tool logic are deferred to Phases 1–2.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InboundFragment:
    """One buffered inbound fragment (already deduped)."""

    message_id: str
    type: str = "text"
    body: str = ""
    media_url: str | None = None
    timestamp: float | None = None


@dataclass(slots=True)
class PipelineResult:
    reply_text: str
    reply_voice: bool = False
    tokens: int = 0
    cost: float = 0.0
    meta: dict = field(default_factory=dict)


def coalesce_fragments(fragments: list[InboundFragment]) -> str:
    """Join buffered fragments into a single turn, in arrival order (§5.2).

    Voice fragments would be transcribed first (STT) in Phase 2; here their
    placeholder text is included so the coalescing behaviour is exercised.
    """
    parts = [f.body.strip() for f in fragments if f.body and f.body.strip()]
    return "\n".join(parts)


async def run_pipeline(
    fragments: list[InboundFragment],
    *,
    catch_up: bool = False,
) -> PipelineResult:
    """Produce a reply for the coalesced fragments.

    Phase 0: echo responder. The ``catch_up`` flag (set by the staleness guard,
    §5.3) short-circuits to a single summary-style reply instead of answering
    stale fragments one by one.

    Plug-in points for later phases:
      1. voice fragments → STT → transcript
      2. images → vision LLM input
      3. language detection (LLM-internal)
      4. RAG retrieve (pgvector, tenant-scoped)
      5. LLM agent + tool loop (max 5 iterations)
      6. TTS render when a voice reply is warranted
    """
    if catch_up:
        return PipelineResult(
            reply_text="Sorry for the delay — how can I help?",
            meta={"catch_up": True},
        )

    coalesced = coalesce_fragments(fragments)
    reply = f"Echo: {coalesced}" if coalesced else "Sorry, I didn't catch that."
    return PipelineResult(reply_text=reply, meta={"echo": True})


__all__ = ["InboundFragment", "PipelineResult", "coalesce_fragments", "run_pipeline"]
