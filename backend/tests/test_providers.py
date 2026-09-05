"""OpenAI-compatible adapter + registry resolution (DESIGN.md §4)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.config import settings
from app.providers.base import ChatMessage
from app.providers.openai_compat import OpenAICompatProvider, ProviderError, ProviderTimeout
from app.providers.registry import (
    PROVIDER_PRESETS,
    resolve_embedding,
    resolve_embedding_identity,
    resolve_llm,
    resolve_llm_identity,
)


def _provider(handler, **kwargs) -> OpenAICompatProvider:
    client = httpx.AsyncClient(
        base_url="https://example.test/v1", transport=httpx.MockTransport(handler)
    )
    return OpenAICompatProvider(
        base_url="https://example.test/v1",
        api_key="key",
        model="gpt-4o-mini",
        client=client,
        **kwargs,
    )


# --- generate(): text, usage, tool calls, vision --------------------------- #
async def test_generate_parses_text_and_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hello there"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    result = await _provider(handler).generate([ChatMessage(role="user", content="hi")])
    assert result.text == "hello there"
    assert result.tool_calls == []
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 4


async def test_generate_parses_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "capture_lead",
                                        "arguments": json.dumps({"phone": "+123"}),
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    result = await _provider(handler).generate([ChatMessage(role="user", content="call me")])
    assert result.text == ""
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "capture_lead"
    assert call.arguments == {"phone": "+123"}


async def test_generate_sends_tools_and_vision_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

    tools = [{"type": "function", "function": {"name": "capture_lead", "parameters": {}}}]
    await _provider(handler).generate(
        [ChatMessage(role="user", content="look", images=["https://img.test/a.png"])],
        tools=tools,
    )
    body = captured["body"]
    assert body["tools"] == tools
    user_msg = body["messages"][0]
    assert user_msg["content"][0] == {"type": "text", "text": "look"}
    assert user_msg["content"][1]["image_url"]["url"] == "https://img.test/a.png"


async def test_generate_tool_role_message_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

    await _provider(handler).generate(
        [ChatMessage(role="tool", content='{"status": "ok"}', tool_call_id="call_1")]
    )
    assert captured["body"]["messages"][0] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"status": "ok"}',
    }


# --- embed() ---------------------------------------------------------------- #
async def test_embed_returns_vectors_in_index_order():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    vectors = await _provider(handler).embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.4, 0.5]]


# --- retries / errors -------------------------------------------------------- #
async def test_retry_on_5xx_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = _provider(handler, max_retries=2, retry_base_seconds=0.0)
    result = await provider.generate([ChatMessage(role="user", content="hi")])
    assert result.text == "ok"
    assert calls["n"] == 2


async def test_retries_exhausted_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = _provider(handler, max_retries=1, retry_base_seconds=0.0)
    with pytest.raises(ProviderError):
        await provider.generate([ChatMessage(role="user", content="hi")])


async def test_client_error_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    provider = _provider(handler, max_retries=2, retry_base_seconds=0.0)
    with pytest.raises(ProviderError):
        await provider.generate([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 1


async def test_timeout_raises_provider_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    provider = _provider(handler, max_retries=0, retry_base_seconds=0.0)
    with pytest.raises(ProviderTimeout):
        await provider.generate([ChatMessage(role="user", content="hi")])


# --- registry ---------------------------------------------------------------- #
def test_resolve_llm_falls_back_to_settings():
    provider = resolve_llm(None)
    assert provider._model == settings.llm_model  # noqa: SLF001


def test_resolve_llm_uses_flat_tenant_config_columns():
    class FakeConfig:
        llm_provider = "groq"
        llm_model = "llama-3.1-8b-instant"
        providers = {}

    provider = resolve_llm(FakeConfig())
    assert provider._model == "llama-3.1-8b-instant"  # noqa: SLF001
    assert provider._base_url == PROVIDER_PRESETS["groq"]  # noqa: SLF001


def test_resolve_llm_prefers_providers_json_override():
    class FakeConfig:
        llm_provider = "groq"
        llm_model = "llama-3.1-8b-instant"
        providers = {"llm": {"provider": "openrouter", "model": "gpt-4o-mini"}}

    provider = resolve_llm(FakeConfig())
    assert provider._base_url == PROVIDER_PRESETS["openrouter"]  # noqa: SLF001
    assert provider._model == "gpt-4o-mini"  # noqa: SLF001


def test_resolve_llm_custom_base_url():
    class FakeConfig:
        llm_provider = "custom"
        llm_model = "my-model"
        providers = {"llm": {"base_url": "https://my-llm.internal/v1"}}

    provider = resolve_llm(FakeConfig())
    assert provider._base_url == "https://my-llm.internal/v1"  # noqa: SLF001


def test_resolve_embedding_falls_back_to_settings():
    provider = resolve_embedding(None)
    assert provider._model == settings.embedding_model  # noqa: SLF001
    assert provider._base_url == PROVIDER_PRESETS["openai"]  # noqa: SLF001


# --- pricing identity -------------------------------------------------------- #
def test_llm_identity_matches_the_provider_actually_used():
    """Cost must be priced against the model that answered.

    ``resolve_llm`` prefers ``providers["llm"]`` over the flat columns, but the
    pipeline used to read the flat columns directly when pricing. A tenant
    configured through the nested map was therefore billed against a different
    model than the one that ran -- usually $0.00, because the wrong name misses
    the pricing table entirely.
    """

    class FakeConfig:
        llm_provider = "groq"
        llm_model = "llama-3.1-8b-instant"
        providers = {"llm": {"provider": "gemini", "model": "gemini-2.5-flash"}}

    config = FakeConfig()
    provider_name, model = resolve_llm_identity(config)

    assert (provider_name, model) == ("gemini", "gemini-2.5-flash")
    assert model == resolve_llm(config)._model  # noqa: SLF001


def test_llm_identity_falls_back_to_flat_columns_then_settings():
    class FlatConfig:
        llm_provider = "groq"
        llm_model = "llama-3.1-8b-instant"
        providers = {}

    assert resolve_llm_identity(FlatConfig()) == ("groq", "llama-3.1-8b-instant")
    assert resolve_llm_identity(None) == (settings.llm_provider, settings.llm_model)


# --- embeddings are billed too ------------------------------------------------ #
async def test_embed_reports_the_tokens_it_was_billed_for():
    """embed() returned only vectors, so every RAG query and every ingested
    chunk was billed and recorded as nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 37, "total_tokens": 37},
            },
        )

    provider = _provider(handler)
    vectors, usage = await provider.embed_with_usage(["what time do you open?"])

    assert vectors == [[0.1, 0.2]]
    assert usage.prompt_tokens == 37


async def test_embed_without_usage_reports_zero_rather_than_guessing():
    """Some OpenAI-compatible providers omit usage on embeddings. Recording a
    guess would be worse than recording nothing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})

    vectors, usage = await _provider(handler).embed_with_usage(["hi"])

    assert vectors == [[0.1]]
    assert usage.prompt_tokens == 0


def test_embedding_identity_matches_the_provider_actually_used():
    """There are no flat embedding columns on tenant_config -- only the nested
    providers map -- so pricing must resolve it the same way the client does."""

    class FakeConfig:
        llm_provider = None
        llm_model = None
        providers = {"embedding": {"provider": "openai", "model": "text-embedding-3-small"}}

    config = FakeConfig()
    assert resolve_embedding_identity(config) == ("openai", "text-embedding-3-small")
    assert resolve_embedding_identity(None) == (
        settings.embedding_provider,
        settings.embedding_model,
    )
