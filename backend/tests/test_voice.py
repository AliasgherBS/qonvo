"""Phase 2 voice: STT/TTS resolution + pipeline voice helpers (DESIGN.md §2, §4)."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.providers import registry
from app.workers import pipeline
from app.workers.pipeline import (
    InboundFragment,
    compute_stt_cost,
    compute_tts_cost,
    is_voice_fragment,
    should_reply_voice,
)


# --- pure helpers ---------------------------------------------------------------- #
def test_is_voice_fragment():
    assert is_voice_fragment(InboundFragment(message_id="1", type="ptt", media_url="http://a"))
    assert is_voice_fragment(InboundFragment(message_id="1", type="voice", media_url="http://a"))
    assert not is_voice_fragment(InboundFragment(message_id="1", type="voice"))  # no media
    assert not is_voice_fragment(InboundFragment(message_id="1", type="text", media_url="http://a"))


@pytest.mark.parametrize(
    "mode,had_voice,expected",
    [
        ("always", False, True),
        ("always", True, True),
        ("never", True, False),
        ("never", False, False),
        ("match", True, True),
        ("match", False, False),
    ],
)
def test_should_reply_voice(mode, had_voice, expected):
    assert should_reply_voice(mode, inbound_had_voice=had_voice) is expected


# --- provider resolution (None = capability disabled) ---------------------------- #
def test_resolve_stt_none_without_key(monkeypatch):
    monkeypatch.setattr(registry.settings, "stt_api_key", None)
    assert registry.resolve_stt(None) is None


def test_resolve_stt_builds_with_key(monkeypatch):
    monkeypatch.setattr(registry.settings, "stt_api_key", "sk-test")
    stt = registry.resolve_stt(None)
    assert stt is not None
    assert type(stt).__name__ == "OpenAICompatSTT"


def test_resolve_tts_none_without_key(monkeypatch):
    monkeypatch.setattr(registry.settings, "tts_api_key", None)
    assert registry.resolve_tts(None) is None


def test_resolve_tts_builds_with_key(monkeypatch):
    monkeypatch.setattr(registry.settings, "tts_api_key", "sk-test")
    tts = registry.resolve_tts(None)
    assert tts is not None and type(tts).__name__ == "OpenAICompatTTS"


def test_voice_reply_mode_prefers_tenant_override():
    tc = SimpleNamespace(providers={"voice": {"mode": "always"}}, llm_provider=None, llm_model=None)
    assert registry.voice_reply_mode(tc) == "always"


# --- transcription (voice-in) ---------------------------------------------------- #
async def test_transcribe_sets_body_from_stt(monkeypatch):
    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock(
        return_value=SimpleNamespace(text="I want to book", language="en")
    )
    monkeypatch.setattr(registry, "resolve_stt", lambda _tc: fake_stt)

    waha = AsyncMock()
    waha.download_media = AsyncMock(return_value=b"oggbytes")

    frags = [InboundFragment(message_id="1", type="ptt", media_url="http://waha/media")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    had_voice, seconds = await pipeline._transcribe_voice_fragments(frags, None, waha, bound)

    assert had_voice is True
    assert seconds >= 1  # metered from audio byte length
    assert frags[0].body == "I want to book"
    assert frags[0].type == "voice"
    waha.download_media.assert_awaited_once()


async def test_transcribe_no_voice_fragments_returns_false():
    frags = [InboundFragment(message_id="1", type="text", body="hi")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    assert await pipeline._transcribe_voice_fragments(frags, None, None, bound) == (False, 0)


async def test_transcribe_without_stt_degrades_to_text(monkeypatch):
    monkeypatch.setattr(registry, "resolve_stt", lambda _tc: None)
    waha = AsyncMock()
    frags = [InboundFragment(message_id="1", type="ptt", media_url="http://a")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    had_voice, seconds = await pipeline._transcribe_voice_fragments(frags, None, waha, bound)
    assert had_voice is True  # voice was present...
    assert seconds == 0  # ...but nothing transcribed, so nothing metered
    assert frags[0].body == ""  # ...but not transcribed


async def test_transcribe_skips_oversized_audio(monkeypatch):
    from app.core.config import settings

    fake_stt = AsyncMock()
    fake_stt.transcribe = AsyncMock()
    monkeypatch.setattr(registry, "resolve_stt", lambda _tc: fake_stt)
    waha = AsyncMock()
    waha.download_media = AsyncMock(
        return_value=b"x" * (settings.max_inbound_audio_bytes + 1)
    )
    frags = [InboundFragment(message_id="1", type="ptt", media_url="http://a")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    had_voice, seconds = await pipeline._transcribe_voice_fragments(frags, None, waha, bound)
    assert had_voice is True
    assert seconds == 0  # over the cap → never metered
    fake_stt.transcribe.assert_not_awaited()  # never sent to STT


# --- synthesis (voice-out) ------------------------------------------------------- #
async def test_synthesize_reply_returns_base64(monkeypatch):
    fake_tts = AsyncMock()
    fake_tts.synthesize = AsyncMock(return_value=b"opusaudio")
    monkeypatch.setattr(registry, "resolve_tts", lambda _tc: fake_tts)
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)

    out = await pipeline._synthesize_reply("your appointment is booked", None, bound)
    assert out == base64.b64encode(b"opusaudio").decode()


async def test_synthesize_reply_none_without_tts(monkeypatch):
    monkeypatch.setattr(registry, "resolve_tts", lambda _tc: None)
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    assert await pipeline._synthesize_reply("hi", None, bound) is None


# --------------------------------------------------------------------------- #
# Vision: inbound images inlined as data URIs (LLM can't reach WAHA's host)
# --------------------------------------------------------------------------- #
def test_sniff_image_mime():
    assert pipeline._sniff_image_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert pipeline._sniff_image_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert pipeline._sniff_image_mime(b"GIF89a...") == "image/gif"
    assert pipeline._sniff_image_mime(b"RIFF\x00\x00\x00\x00WEBPvp8") == "image/webp"
    assert pipeline._sniff_image_mime(b"unknownbytes") == "image/jpeg"


async def test_images_as_data_uris_downloads_and_inlines():
    waha = AsyncMock()
    waha.download_media = AsyncMock(return_value=b"\xff\xd8\xffjpegdata")
    frags = [InboundFragment(message_id="1", type="image", media_url="http://waha/x")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    uris = await pipeline._images_as_data_uris(frags, waha, bound)
    assert len(uris) == 1
    assert uris[0].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(uris[0].split(",", 1)[1]) == b"\xff\xd8\xffjpegdata"


async def test_images_as_data_uris_skips_oversized(monkeypatch):
    from app.core.config import settings

    waha = AsyncMock()
    waha.download_media = AsyncMock(return_value=b"x" * (settings.max_inbound_image_bytes + 1))
    frags = [InboundFragment(message_id="1", type="image", media_url="http://waha/x")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    assert await pipeline._images_as_data_uris(frags, waha, bound) == []


async def test_images_as_data_uris_empty_without_images():
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)
    frags = [InboundFragment(message_id="1", type="text", body="hi")]
    assert await pipeline._images_as_data_uris(frags, AsyncMock(), bound) == []


# --- audio is billed too, in different units ---------------------------------- #
# STT is priced per minute of audio and TTS per million characters, so neither
# fits the per-token table. Both were recorded as $0.00, and for a tenant with
# voice replies on, TTS is the single largest line in the bill.
_STT = {"groq": {"whisper-large-v3": {"per_minute": 0.00185}}}
_TTS = {"openai": {"tts-1": {"per_1m_chars": 15.0}}}


def test_stt_is_billed_by_the_second_not_the_whole_minute():
    """A 30-second voice note must cost half a minute, not a full one."""
    cost = compute_stt_cost("groq", "whisper-large-v3", 30, pricing=_STT)

    assert cost == pytest.approx(0.00185 / 2)


def test_tts_is_billed_per_character():
    cost = compute_tts_cost("openai", "tts-1", 400, pricing=_TTS)

    assert cost == pytest.approx(400 / 1_000_000 * 15.0)


def test_an_unpriced_audio_model_records_zero_loudly():
    """Same contract as the token table: a miss is 0.00 with a warning, so it
    surfaces as a bug rather than as suspiciously cheap analytics."""
    assert compute_stt_cost("groq", "not-a-model", 60, pricing=_STT) == 0.0
    assert compute_tts_cost("openai", "not-a-model", 400, pricing=_TTS) == 0.0


def test_no_audio_means_no_charge():
    assert compute_stt_cost("groq", "whisper-large-v3", 0, pricing=_STT) == 0.0
    assert compute_tts_cost("openai", "tts-1", 0, pricing=_TTS) == 0.0


def test_the_shipped_table_prices_the_models_we_actually_run():
    """The configured STT and TTS models must be priced, or every voice turn
    silently records nothing -- which is how this gap existed in the first place."""
    from app.core.config import settings

    assert compute_stt_cost(settings.stt_provider, settings.stt_model, 60) > 0
    assert compute_tts_cost(settings.tts_provider, settings.tts_model, 1000) > 0
