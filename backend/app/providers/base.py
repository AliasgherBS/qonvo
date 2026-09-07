"""Provider abstraction layer — abstract interfaces only (DESIGN.md §4).

Phase 0 defines the contracts so the pipeline can depend on stable interfaces;
concrete adapters (OpenAI, Gemini, Groq, Uplift AI, ...) land in later phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    # Optional image inputs (URLs or data URIs) for vision-capable models.
    images: list[str] = field(default_factory=list)
    # Tool-loop round-trip fields (Phase 1, DESIGN.md §5.4 step 7): an
    # "assistant" message that requested tool calls carries them here; the
    # corresponding "tool" role reply carries ``tool_call_id``/``name``.
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(slots=True)
class LLMResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Part of ``prompt_tokens`` the provider served from its automatic prompt
    #: cache, billed at roughly a tenth of the input rate. 0 when the provider
    #: does not report it.
    cached_tokens: int = 0


@dataclass(slots=True)
class EmbeddingUsage:
    """Tokens billed for one embedding call. 0 when the provider omits usage."""

    prompt_tokens: int = 0


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None = None


class LLMProvider(ABC):
    """``generate(messages, tools, model) → text + tool_calls`` (must support vision)."""

    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> LLMResult: ...


class STTProvider(ABC):
    """``transcribe(audio) → text + lang``."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        *,
        mimetype: str = "audio/ogg",
        language_hint: str | None = None,
    ) -> TranscriptionResult: ...


class TTSProvider(ABC):
    """``synthesize(text, voice, lang) → audio`` (OPUS/OGG for WhatsApp voice)."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> bytes: ...


class EmbeddingProvider(ABC):
    """``embed(texts) → vectors`` for pgvector retrieval."""

    @abstractmethod
    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]: ...


__all__ = [
    "ChatMessage",
    "EmbeddingProvider",
    "LLMProvider",
    "LLMResult",
    "STTProvider",
    "TTSProvider",
    "ToolCall",
    "TranscriptionResult",
]
