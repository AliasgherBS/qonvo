"""Voice metering: what a voice reply costs the allowance (spec §1).

Two live bugs on 2026-09-08, both in this seam.

**The arithmetic.** A customer sent one Urdu voice note, the rep replied with
one voice note of about 39 seconds, and ``usage_counters.voice_seconds`` went
to 986 -- 17 minutes against a 5 minute allowance, in red, from a single
message. The meter divided the audio's byte length by a fixed
``voice_bytes_per_second = 2000``, a figure calibrated for the ~16 kbps OPUS
that WhatsApp voice notes arrive in, and then applied it to a TTS reply too.
With ``QONVO_TTS_FORMAT=wav`` the reply is not compressed at all: 24 kHz
16-bit mono PCM is 48,000 bytes a second, so every second of synthesis metered
as twenty-four. These tests pin the arithmetic in seconds, and pin the wrong
answer explicitly so a reintroduced constant fails loudly rather than quietly.

**The leak.** When the allowance ran out the rep correctly degraded to text,
and then told the *customer* "Voice replies are paused until your plan
renews". That is the business's commercial state, announced to the business's
own customer. The test below asserts the reply the customer receives is never
rebound from anything to do with the allowance.
"""

from __future__ import annotations

import ast
import io
import pathlib
import struct
import types
import uuid
import wave

import pytest
from app.agent.audio_meter import (
    OPUS_GRANULE_RATE,
    audio_duration_seconds,
    measure_audio_duration,
)
from app.core.config import settings

# --------------------------------------------------------------------------- #
# Builders: real containers, so the parsers are exercised and not mocked
# --------------------------------------------------------------------------- #
_TTS_SAMPLE_RATE = 24_000  # what Groq's orpheus / OpenAI tts-1 actually return
_TTS_BYTES_PER_SECOND = _TTS_SAMPLE_RATE * 2  # 16-bit mono = 48,000 B/s


def _wav(seconds: float, *, rate: int = _TTS_SAMPLE_RATE, channels: int = 1) -> bytes:
    """A real WAV of ``seconds``, silent. Size is what the old meter read."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * channels * int(rate * seconds))
    return buf.getvalue()


def _ogg_page(*, granule: int, page_type: int, seq: int, payload: bytes) -> bytes:
    """One Ogg page. CRC is left zero: nothing here verifies it, and a real
    checksum would test the test rather than the parser."""
    segments = bytearray()
    remaining = len(payload)
    while remaining >= 255:
        segments.append(255)
        remaining -= 255
    segments.append(remaining)
    return (
        b"OggS"
        + bytes([0, page_type])
        + struct.pack("<q", granule)
        + struct.pack("<I", 0xCAFE)  # serial
        + struct.pack("<I", seq)
        + struct.pack("<I", 0)  # crc
        + bytes([len(segments)])
        + bytes(segments)
        + payload
    )


def _ogg_opus(seconds: float, *, pre_skip: int = 312) -> bytes:
    """An Ogg/Opus stream whose last page's granule encodes ``seconds``.

    This is the shape of a WhatsApp voice note: the only thing that carries the
    duration is the final page's granule position, counted at a fixed 48 kHz
    regardless of the audio's own rate, and offset by the pre-skip samples the
    decoder throws away.
    """
    head = (
        b"OpusHead"
        + bytes([1, 1])  # version, channels
        + struct.pack("<H", pre_skip)
        + struct.pack("<I", 48_000)
        + struct.pack("<h", 0)
        + bytes([0])
    )
    granule = int(seconds * OPUS_GRANULE_RATE) + pre_skip
    return _ogg_page(granule=0, page_type=2, seq=0, payload=head) + _ogg_page(
        granule=granule, page_type=4, seq=1, payload=b"\xfc" * 64
    )


# --------------------------------------------------------------------------- #
# Bug 1: the arithmetic. A 39 second reply is 39 seconds.
# --------------------------------------------------------------------------- #
def test_a_thirty_nine_second_wav_reply_meters_thirty_nine_seconds():
    """The exact number from the live incident.

    Not 936 (the byte estimate that was recorded), not 2,340 (39 minutes read
    as seconds), not 39,000 (milliseconds), not 1,014 (the reply's characters).
    Thirty-nine.
    """
    audio = _wav(39)

    assert audio_duration_seconds(audio) == 39

    # And the specific wrong answers, named so a regression says which one.
    assert audio_duration_seconds(audio) != 936  # bytes / 2000
    assert audio_duration_seconds(audio) != 39 * 60  # minutes stored as seconds
    assert audio_duration_seconds(audio) != 39_000  # milliseconds


def test_the_old_byte_estimate_is_the_number_the_owner_saw():
    """Documents the defect rather than the fix: this is the calculation the
    pipeline used to do, and it is 24x out for a WAV reply.

    986 seconds landed in ``usage_counters`` for one 39 second reply plus three
    short inbound notes. ceil(986/60) = 17, which is the "17 of 5 minutes" the
    dashboard showed and the "voice paused: 17/5 min used" in the worker log.
    """
    audio = _wav(39)
    old_estimate = max(1, len(audio) // settings.voice_bytes_per_second)

    assert old_estimate == 936
    assert old_estimate / audio_duration_seconds(audio) == pytest.approx(24, abs=0.1)
    # The whole 5 minute allowance, from one message.
    assert old_estimate > 5 * 60


@pytest.mark.parametrize("seconds", [1, 3, 8, 39, 120])
def test_wav_duration_is_exact_at_every_length(seconds: int):
    assert audio_duration_seconds(_wav(seconds)) == seconds


def test_wav_rate_and_channels_do_not_change_the_answer():
    """The reason a bytes-per-second constant cannot be repaired by choosing a
    better number: three of its inputs are provider- and tenant-configurable.
    Ten seconds is ten seconds at any of them."""
    variants = [
        _wav(10, rate=8_000),
        _wav(10, rate=24_000),
        _wav(10, rate=44_100),
        _wav(10, rate=48_000, channels=2),
    ]
    assert [audio_duration_seconds(v) for v in variants] == [10, 10, 10, 10]
    # Sizes span 12x, so anything reading length would disagree with itself.
    assert max(len(v) for v in variants) / min(len(v) for v in variants) > 10


def test_ogg_opus_duration_comes_from_the_granule():
    """The inbound leg: a WhatsApp voice note carries no length in its bytes,
    only a granule count on the last page."""
    assert audio_duration_seconds(_ogg_opus(10)) == 10
    assert measure_audio_duration(_ogg_opus(7.25)) == pytest.approx(7.25)


def test_the_pre_skip_is_subtracted():
    """Granules count from before the samples the decoder discards, so leaving
    the pre-skip in overstates every note by a few milliseconds. Small, but it
    is the difference between exact and nearly."""
    assert measure_audio_duration(_ogg_opus(5, pre_skip=6_000)) == pytest.approx(5.0)


def test_partial_seconds_round_up_and_never_to_zero():
    """A quarter-second reply still cost a provider call. Metering it as zero
    would let a run of one-word voice replies cost the allowance nothing."""
    assert audio_duration_seconds(_wav(0.25)) == 1
    assert audio_duration_seconds(_wav(2.1)) == 3
    assert audio_duration_seconds(b"") == 0


# --------------------------------------------------------------------------- #
# Bug 1: robustness. Metering must never be able to cost a customer a reply.
# --------------------------------------------------------------------------- #
def test_a_streamed_wav_with_a_placeholder_length_uses_the_bytes_that_arrived():
    """A WAV written to a stream cannot know its own data length, so it writes
    0 or 0xFFFFFFFF. Believing the header would meter a 39 second reply as
    nothing at all -- the failure mode opposite to the one just fixed."""
    audio = bytearray(_wav(39))
    struct.pack_into("<I", audio, 40, 0xFFFFFFFF)  # data chunk size field
    assert audio_duration_seconds(bytes(audio)) == 39

    struct.pack_into("<I", audio, 40, 0)
    assert audio_duration_seconds(bytes(audio)) == 39


def test_an_unparseable_container_falls_back_to_the_estimate():
    """mp3 and aac are not parsed. A rough number still beats no metering at
    all: unmetered voice is why the allowance exists."""
    mp3ish = b"\xff\xfb\x90\x00" + b"\x00" * 39_996
    assert measure_audio_duration(mp3ish) is None
    assert audio_duration_seconds(mp3ish) == 20  # 40,000 bytes / 2000
    assert audio_duration_seconds(mp3ish, bytes_per_second=4_000) == 10


@pytest.mark.parametrize(
    "data",
    [
        b"RIFF",  # truncated in the header
        b"RIFF\x00\x00\x00\x00WAVE",  # no chunks at all
        b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00" + b"\x00" * 16,  # no data chunk
        b"OggS",  # truncated page
        b"OggS" + b"\x00" * 60,  # zero granule
        b"\x00" * 500,  # not audio
    ],
)
def test_corrupt_audio_is_a_cannot_measure_not_an_exception(data: bytes):
    assert measure_audio_duration(data) is None
    audio_duration_seconds(data)  # must not raise


def test_a_zero_length_wav_chunk_does_not_loop_forever():
    """A malformed chunk header advances the cursor by zero. Without the guard
    the parser spins and the worker never finishes the turn."""
    bad = b"RIFF\x00\x00\x00\x00WAVEjunk\x00\x00\x00\x00"
    assert measure_audio_duration(bad) is None


# --------------------------------------------------------------------------- #
# Bug 1, wired up: the pipeline's two legs both measure
# --------------------------------------------------------------------------- #
async def test_transcribing_meters_the_note_not_its_size(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.providers import registry
    from app.workers import pipeline

    note = _ogg_opus(11)
    stt = AsyncMock()
    stt.transcribe = AsyncMock(return_value=SimpleNamespace(text="salaam", language="ur"))
    monkeypatch.setattr(registry, "resolve_stt", lambda _tc: stt)

    waha = AsyncMock()
    waha.download_media = AsyncMock(return_value=note)
    frags = [pipeline.InboundFragment(message_id="1", type="ptt", media_url="http://a")]
    bound = SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None)

    had_voice, seconds = await pipeline._transcribe_voice_fragments(frags, None, waha, bound)
    assert had_voice is True
    assert seconds == 11


def test_the_pipeline_meters_the_reply_through_the_measured_helper():
    """The voice-out leg must call the meter, not divide by a constant.

    Pinned structurally because the alternative is a full pipeline turn, which
    needs a live Postgres and so does not run by default -- and this bug shipped
    precisely because nothing in the default suite touched the calculation.
    """
    source = pathlib.Path("app/workers/pipeline.py").read_text()

    assert "audio_duration_seconds(reply_audio)" in source
    assert "voice_bytes_per_second" not in source, (
        "the pipeline is estimating from byte length again; the constant is "
        "only correct for one container (see app/agent/audio_meter.py)"
    )


# --------------------------------------------------------------------------- #
# Bug 2: the customer is never told about the tenant's plan
# --------------------------------------------------------------------------- #
def _function_ast(name: str) -> ast.AST:
    tree = ast.parse(pathlib.Path("app/workers/pipeline.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in pipeline.py")


def test_nothing_about_the_allowance_is_appended_to_the_customers_reply():
    """The reply the customer receives is what the model produced, unedited.

    The regression was one line: ``reply_text = f"{reply_text}{voice_quota_note}"``.
    So the invariant is that ``reply_text`` is never rebound from anything
    named for the allowance, the quota or a notice.
    """
    leaky = ("quota", "allowance", "notice", "notify")
    offenders = []
    for node in ast.walk(_function_ast("_run_pipeline_inner")):
        if isinstance(node, ast.Assign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(t, ast.Name) and t.id == "reply_text" for t in targets):
                continue
            referenced = {
                n.id.lower() for n in ast.walk(node.value) if isinstance(n, ast.Name)
            } | {
                (n.value or "").lower()
                for n in ast.walk(node.value)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            }
            if any(word in ref for ref in referenced for word in leaky):
                offenders.append(ast.unparse(node))

    assert offenders == [], (
        "the customer's reply is being appended to with the tenant's "
        f"commercial state: {offenders}"
    )


def test_the_owner_alert_is_addressed_to_the_owner():
    """The state has to go somewhere, and the owner is the party to whom it
    means anything. Their copy should read as account news, not as an apology
    a customer could ever see."""
    from app.workers import pipeline

    captured: dict[str, object] = {}

    async def _fake_notify(_db, **kwargs):
        captured.update(kwargs)

    class _NullSession:
        async def execute(self, _stmt):
            return types.SimpleNamespace(first=lambda: None)

    class _Ctx:
        async def __aenter__(self):
            return _NullSession()

        async def __aexit__(self, *_exc):
            return False

    import app.services.notifications as notifications

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(notifications, "notify", _fake_notify)
        monkey.setattr(pipeline, "tenant_session", lambda _tid: _Ctx())
        import asyncio
        import datetime as dt

        from app.agent.voice_allowance import VoiceAllowance

        asyncio.run(
            pipeline._notify_voice_quota(
                types.SimpleNamespace(warning=lambda *_a, **_k: None),
                uuid.uuid4(),
                VoiceAllowance(used_seconds=400, allowed_seconds=300),
                now=dt.datetime(2026, 9, 8, 18, 37, tzinfo=dt.UTC),
            )
        )
    finally:
        monkey.undo()

    assert captured["title"] == "Voice replies are paused"
    body = str(captured["body"])
    assert "Your rep" in body  # the owner's rep, not "I"
    assert "Upgrade" in body  # an action only the owner can take
    # Never sent over WhatsApp to the customer's chat.
    assert captured["send_gateway"] is None


def test_the_owner_is_told_once_per_period_not_once_per_message():
    """Live, the owner got the same alert twice in 40 minutes.

    The dedupe looked for an ``auto_reply == "voice_quota"`` marker on past
    messages, and nothing ever wrote that marker, so it was always False. It
    now asks the ``notifications`` table, which is the row being deduped.
    """
    import asyncio
    import datetime as dt

    import app.services.notifications as notifications
    from app.agent.voice_allowance import VoiceAllowance
    from app.workers import pipeline

    sent: list[str] = []

    async def _fake_notify(_db, **kwargs):
        sent.append(str(kwargs["title"]))

    class _SessionWithPriorAlert:
        async def execute(self, _stmt):
            return types.SimpleNamespace(first=lambda: (uuid.uuid4(),))

    class _Ctx:
        async def __aenter__(self):
            return _SessionWithPriorAlert()

        async def __aexit__(self, *_exc):
            return False

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(notifications, "notify", _fake_notify)
        monkey.setattr(pipeline, "tenant_session", lambda _tid: _Ctx())
        asyncio.run(
            pipeline._notify_voice_quota(
                types.SimpleNamespace(warning=lambda *_a, **_k: None),
                uuid.uuid4(),
                VoiceAllowance(used_seconds=400, allowed_seconds=300),
                now=dt.datetime(2026, 9, 8, 19, 14, tzinfo=dt.UTC),
            )
        )
    finally:
        monkey.undo()

    assert sent == []  # already told this period


def test_the_period_boundary_is_the_same_day_in_both_shapes():
    """``usage_counters.day`` is a date and ``notifications.created_at`` is a
    timestamp. If the two boundaries drifted, the alert would re-fire on the
    first of the month before the counters reset, or not at all."""
    import datetime as dt

    from app.agent.voice_allowance import period_start, period_start_dt

    now = dt.datetime(2026, 9, 8, 19, 14, tzinfo=dt.UTC)
    assert period_start(now) == dt.date(2026, 9, 1)
    assert period_start_dt(now) == dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
    assert period_start_dt(now).date() == period_start(now)
    assert period_start_dt(now).tzinfo is dt.UTC  # naive would compare wrong


# --- the provider's own figure wins, and its absence must not break a turn ------- #
def test_the_providers_reported_duration_is_preferred_over_the_bytes():
    """Whisper bills per second of audio it processed, silence included, and
    reports that number. Billing the tenant against anything else guarantees
    the two ledgers disagree. It is the same reason token counts come from an
    LLM response's `usage` block rather than from a local estimate."""
    from app.agent.audio_meter import audio_duration_seconds

    # A file whose bytes say one thing and whose provider says another.
    ten_seconds_of_wav = _wav(10)

    assert audio_duration_seconds(ten_seconds_of_wav) == 10
    assert audio_duration_seconds(ten_seconds_of_wav, reported_seconds=7.2) == 8


def test_a_missing_reported_duration_falls_back_to_measuring():
    from app.agent.audio_meter import audio_duration_seconds

    assert audio_duration_seconds(_wav(10), reported_seconds=None) == 10


async def test_a_result_without_the_field_still_transcribes_and_meters(monkeypatch):
    """The failure this actually caused. The transcription block is wrapped in a
    broad `except` that degrades the turn to text, so reading the field as an
    attribute made an STT result that predated it lose the *transcript* and log
    "transcription failed" for a transcription that had succeeded."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.workers import pipeline
    from app.workers.pipeline import InboundFragment

    stt = AsyncMock()
    # No duration_seconds, as an older provider or any stub would be.
    stt.transcribe = AsyncMock(return_value=SimpleNamespace(text="hello", language="ur"))
    # The pipeline builds its own provider from the registry, so the mock has
    # to be injected there rather than passed in.
    from app.providers import registry

    monkeypatch.setattr(registry, "resolve_stt", lambda _tc: stt)
    waha = AsyncMock()
    waha.download_media = AsyncMock(return_value=_wav(6))
    bound = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)

    frags = [InboundFragment(message_id="1", type="ptt", media_url="http://waha/m")]
    had_voice, seconds = await pipeline._transcribe_voice_fragments(frags, None, waha, bound)

    assert had_voice is True
    assert frags[0].body == "hello", "the transcript must survive a missing field"
    assert seconds == 6, "and it must still meter, by measuring the container"
