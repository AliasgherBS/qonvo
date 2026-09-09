"""How long a piece of audio actually is, for voice metering (spec §1).

Voice minutes used to be metered from the *size* of the audio, via
``settings.voice_bytes_per_second = 2000``. That constant was calibrated for
exactly one format, the ~16 kbps OPUS that WhatsApp voice notes arrive in, and
was then applied to the TTS reply as well. A reply is a different container at
a different bitrate, and with ``QONVO_TTS_FORMAT=wav`` it is not compressed at
all: 24 kHz 16-bit mono PCM is 48,000 bytes a second, twenty-four times the
constant. Live on 2026-09-08 a 39-second reply metered as ~936 seconds and a
five-minute allowance was gone inside one message.

A bytes-per-second constant cannot be fixed by picking a better number,
because the right number depends on the format, the sample rate, the channel
count and the codec's bitrate, and three of those are tenant-configurable. So
measure instead: WAV states its byte rate and its data length in the header,
and an Ogg stream's final page carries a granule position, which for Opus
counts samples at a fixed 48 kHz. Both are exact, and both are a few lines of
stdlib rather than a dependency and an ffmpeg subprocess.

The estimate stays as the fallback for a container we cannot parse (mp3, aac),
because a rough number still beats metering nothing: unmetered voice is how
the allowance came to be needed in the first place.
"""

from __future__ import annotations

import math
import struct

from app.core.config import settings

__all__ = [
    "OPUS_GRANULE_RATE",
    "audio_duration_seconds",
    "measure_audio_duration",
]

#: Opus granule positions are always counted at 48 kHz, whatever the audio's
#: own sample rate. Fixed by RFC 7845, not something to read out of the header.
OPUS_GRANULE_RATE = 48_000


def _wav_duration(data: bytes) -> float | None:
    """Duration from a RIFF/WAVE header: ``data`` chunk length / byte rate."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None

    byte_rate = 0
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        payload = pos + 8

        if chunk_id == b"fmt " and size >= 16:
            # fmt : format(2) channels(2) sample_rate(4) byte_rate(4) ...
            (byte_rate,) = struct.unpack_from("<I", data, payload + 8)
        elif chunk_id == b"data":
            if byte_rate <= 0:
                return None
            # A WAV written to a stream carries a placeholder length (0, or
            # 0xFFFFFFFF) because the writer did not know it yet. Trust the
            # bytes that actually arrived over a header that admits it is
            # guessing, which is what a TTS endpoint returns.
            available = len(data) - payload
            length = size if 0 < size <= available else available
            return length / byte_rate

        if size == 0:
            return None  # malformed: a zero-length chunk would loop forever
        pos = payload + size + (size % 2)  # RIFF chunks are word-aligned

    return None


def _ogg_duration(data: bytes) -> float | None:
    """Duration from an Ogg stream's last page granule position."""
    if len(data) < 14 or data[:4] != b"OggS":
        return None

    last_page = data.rfind(b"OggS")
    if last_page < 0 or last_page + 14 > len(data):
        return None
    # Page header: "OggS"(4) version(1) type(1) granule_position(8, LE signed)
    (granule,) = struct.unpack_from("<q", data, last_page + 6)
    if granule <= 0:
        return None

    head = data.find(b"OpusHead", 0, 1024)
    if head >= 0:
        rate = OPUS_GRANULE_RATE
        if head + 12 <= len(data):
            # Granules count from before the pre-skip samples the decoder
            # discards, so they overstate playable length by that much.
            (pre_skip,) = struct.unpack_from("<H", data, head + 10)
            granule = max(0, granule - pre_skip)
    else:
        vorbis = data.find(b"\x01vorbis", 0, 1024)
        if vorbis < 0 or vorbis + 16 > len(data):
            return None  # some other Ogg codec: let the caller estimate
        (rate,) = struct.unpack_from("<I", data, vorbis + 12)

    return granule / rate if rate > 0 else None


def measure_audio_duration(data: bytes) -> float | None:
    """Exact duration in seconds, or None for a container we do not parse.

    Never raises: a truncated or corrupt file is a "cannot measure", not a
    failed turn. Metering must not be able to cost a customer their reply.
    """
    if not data:
        return 0.0
    for parse in (_wav_duration, _ogg_duration):
        try:
            seconds = parse(data)
        except (struct.error, IndexError, ZeroDivisionError):
            continue
        if seconds is not None and seconds >= 0:
            return seconds
    return None


def audio_duration_seconds(
    data: bytes,
    *,
    bytes_per_second: int | None = None,
    reported_seconds: float | None = None,
) -> int:
    """Metered whole seconds for ``data``, from the best source available.

    In order: what the provider said, what the container says, and only then an
    estimate from the byte count.

    ``reported_seconds`` wins because it is the figure the provider bills
    *us* against, silence included, so billing the tenant against anything
    else guarantees the two ledgers disagree. It is the same reason token
    counts are read out of an LLM response's ``usage`` block rather than
    estimated locally, which this codebase already does for text. Transcription
    is the only leg that has one: synthesis is given text and returns audio, so
    there is nothing for the provider to report and the container is the best
    available truth.

    Rounded up, and never below 1 for non-empty audio. Up, because a partial
    second still costs a provider call, and rounding down would let a run of
    one-word replies meter as nothing at all. Whisper is itself billed per
    second with no minimum, so rounding up per message is marginally
    conservative in the tenant's disfavour; over a month of whole voice notes
    the difference is seconds, and the alternative rounds our own cost away.
    """
    if not data and reported_seconds is None:
        return 0
    seconds = reported_seconds
    if seconds is None:
        seconds = measure_audio_duration(data)
    if seconds is None:
        rate = bytes_per_second or settings.voice_bytes_per_second
        seconds = len(data) / rate if rate > 0 else 0.0
    return max(1, math.ceil(seconds))
