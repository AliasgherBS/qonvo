"""OpenAI-compatible provider adapter (DESIGN.md §4).

Covers OpenAI, OpenRouter, Groq, and Gemini's OpenAI-compat endpoint, plus any
custom ``base_url`` — they all speak the same ``/chat/completions`` and
``/embeddings`` request/response shape. Async httpx, typed errors, retries with
exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import (
    ChatMessage,
    EmbeddingProvider,
    LLMProvider,
    LLMResult,
    ToolCall,
)


class ProviderError(Exception):
    """Non-retryable (or retries-exhausted) failure from a provider call."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderTimeout(ProviderError):
    """The provider did not respond within the configured timeout."""


def _message_to_payload(message: ChatMessage) -> dict[str, Any]:
    """Convert a :class:`ChatMessage` into an OpenAI chat-completions message.

    Plain text-only messages are sent as a bare string ``content`` (matches the
    minimal shape most OpenAI-compatible servers expect); messages carrying
    image inputs use the multi-part ``content`` array (vision, DESIGN.md §4).
    ``tool`` role and tool-calling ``assistant`` messages carry the extra
    round-trip fields a tool loop needs (DESIGN.md §5.4 step 7).
    """
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.content,
        }

    payload: dict[str, Any] = {"role": message.role}
    if message.images:
        parts: list[dict[str, Any]] = []
        if message.content:
            parts.append({"type": "text", "text": message.content})
        for image in message.images:
            parts.append({"type": "image_url", "image_url": {"url": image}})
        payload["content"] = parts
    else:
        payload["content"] = message.content

    if message.role == "assistant" and message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    return payload


def _parse_tool_calls(raw_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
    if not raw_calls:
        return []
    parsed: list[ToolCall] = []
    for call in raw_calls:
        function = call.get("function", {})
        raw_arguments = function.get("arguments", "{}")
        arguments: dict[str, Any]
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments) if raw_arguments else {}
            except json.JSONDecodeError:
                arguments = {}
        else:
            arguments = raw_arguments or {}
        parsed.append(
            ToolCall(
                id=call.get("id", ""),
                name=function.get("name", ""),
                arguments=arguments,
            )
        )
    return parsed


class OpenAICompatProvider(LLMProvider, EmbeddingProvider):
    """One adapter for any OpenAI-compatible ``/chat/completions`` + ``/embeddings`` API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout if timeout is not None else settings.provider_timeout_seconds
        self._max_retries = (
            max_retries if max_retries is not None else settings.provider_max_retries
        )
        self._retry_base = (
            retry_base_seconds
            if retry_base_seconds is not None
            else settings.provider_retry_base_seconds
        )
        self._external_client = client
        self._client = client

    async def __aenter__(self) -> OpenAICompatProvider:
        self._ensure_client()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.post(path, json=payload)
            except httpx.TimeoutException as exc:
                last_exc = ProviderTimeout(f"{path} timed out: {exc}")
            except httpx.HTTPError as exc:
                last_exc = ProviderError(f"{path} request failed: {exc}")
            else:
                if resp.status_code >= 500:
                    last_exc = ProviderError(
                        f"{path} failed ({resp.status_code}): {resp.text}",
                        status_code=resp.status_code,
                    )
                elif resp.status_code >= 400:
                    # Client errors (bad request, auth, rate limit) are not retried.
                    raise ProviderError(
                        f"{path} failed ({resp.status_code}): {resp.text}",
                        status_code=resp.status_code,
                    )
                else:
                    return resp.json()

            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_base * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": model or self._model,
            "messages": [_message_to_payload(m) for m in messages],
        }
        if tools:
            payload["tools"] = tools

        data = await self._post("/chat/completions", payload)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})
        return LLMResult(
            text=msg.get("content") or "",
            tool_calls=_parse_tool_calls(msg.get("tool_calls")),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        # Pin the output dimension to the pgvector column width — models default
        # to different sizes (e.g. gemini-embedding-001 → 3072, ours is 1536).
        from app.models.knowledge import EMBEDDING_DIM

        payload = {"model": model or self._model, "input": texts, "dimensions": EMBEDDING_DIM}
        data = await self._post("/embeddings", payload)
        items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items]


__all__ = ["OpenAICompatProvider", "ProviderError", "ProviderTimeout"]
