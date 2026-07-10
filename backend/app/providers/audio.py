"""OpenAI-compatible STT + TTS adapters (DESIGN.md §4, Phase 2 voice).

STT (`/audio/transcriptions`) and TTS (`/audio/speech`) are the OpenAI audio
surface, shared by Groq (Whisper STT, PlayAI TTS) and OpenAI. A custom base_url
covers others. NOTE: Gemini's OpenAI-compat endpoint does NOT expose these, so
voice needs an OpenAI/Groq-style key even when the LLM is Gemini.

Async httpx with retries/backoff, mirroring OpenAICompatProvider.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base import STTProvider, TranscriptionResult, TTSProvider
from app.providers.openai_compat import ProviderError, ProviderTimeout


class _AudioClientMixin:
    _base_url: str
    _api_key: str
    _timeout: float
    _max_retries: int
    _retry_base: float
    _external_client: httpx.AsyncClient | None
    _client: httpx.AsyncClient | None

    def _init_http(
        self,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None,
        timeout: float | None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout if timeout is not None else settings.provider_timeout_seconds
        self._max_retries = settings.provider_max_retries
        self._retry_base = settings.provider_retry_base_seconds
        self._external_client = client
        self._client = client

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

    async def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        client = self._ensure_client()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await client.post(path, **kwargs)
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
                    raise ProviderError(
                        f"{path} failed ({resp.status_code}): {resp.text}",
                        status_code=resp.status_code,
                    )
                else:
                    return resp
            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_base * (2**attempt))
        assert last_exc is not None
        raise last_exc


class OpenAICompatSTT(_AudioClientMixin, STTProvider):
    """Whisper-style transcription over ``/audio/transcriptions`` (multipart)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> None:
        self._model = model
        self._init_http(base_url, api_key, client, timeout)

    async def transcribe(
        self,
        audio: bytes,
        *,
        mimetype: str = "audio/ogg",
        language_hint: str | None = None,
    ) -> TranscriptionResult:
        files = {"file": ("audio.ogg", audio, mimetype)}
        data: dict[str, Any] = {"model": self._model, "response_format": "verbose_json"}
        if language_hint:
            data["language"] = language_hint
        resp = await self._post("/audio/transcriptions", files=files, data=data)
        body = resp.json()
        return TranscriptionResult(text=body.get("text") or "", language=body.get("language"))


class OpenAICompatTTS(_AudioClientMixin, TTSProvider):
    """Speech synthesis over ``/audio/speech`` → OPUS bytes for WhatsApp voice."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        voice: str = "alloy",
        response_format: str = "opus",
        client: httpx.AsyncClient | None = None,
        timeout: float | None = None,
    ) -> None:
        self._model = model
        self._voice = voice
        self._response_format = response_format
        self._init_http(base_url, api_key, client, timeout)

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> bytes:
        payload = {
            "model": self._model,
            "input": text,
            "voice": voice or self._voice,
            "response_format": self._response_format,
        }
        resp = await self._post("/audio/speech", json=payload)
        return resp.content


__all__ = ["OpenAICompatSTT", "OpenAICompatTTS"]
