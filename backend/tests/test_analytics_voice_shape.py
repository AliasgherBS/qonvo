"""Analytics answers "what does a message actually look like".

An owner cannot act on "1,247 messages". They can act on "your customers send
20-second voice notes and your rep replies in about 260 characters", because
that is the shape of the thing they are selling.

Two details the implementation gets right and would be easy to get wrong:

  * length() reads coalesce(body, transcript). A voice message stores its words
    in `transcript`, so measuring `body` alone reports every voice note as zero
    characters -- the exact messages this feature exists to describe.
  * inbound and outbound voice seconds are separate columns. `voice_seconds`
    counts only generated audio since 0016 made the allowance bound generation,
    so reusing it for "how long is a customer's voice note" would report the
    rep's own speech back as the customer's.
"""

from __future__ import annotations

import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1] / "app/api/analytics.py").read_text()


def test_length_falls_back_to_the_transcript():
    assert "func.coalesce(Message.body, Message.transcript)" in SRC


def test_inbound_and_outbound_voice_are_not_conflated():
    assert '"voice_seconds_in": r.voice_seconds_in or 0' in SRC
    assert '"voice_seconds_out": r.voice_seconds or 0' in SRC


def test_the_average_is_guarded_against_no_voice_at_all():
    """A tenant that has never received a voice note must read 0, not divide by
    zero and 500 the whole page."""
    assert "round(seconds / n) if n else 0" in SRC


def test_it_is_scoped_to_the_tenant():
    """The shape query joins conversations, which is where tenant_id lives for a
    message. Losing that filter would show one business another's traffic."""
    assert "Conversation.tenant_id == tenant_id, Message.created_at >= start_at" in SRC


def test_the_pipeline_records_both_directions():
    pipe = (
        pathlib.Path(__file__).resolve().parents[1] / "app/workers/pipeline.py"
    ).read_text()
    assert "voice_seconds_in=inbound_voice_seconds" in pipe
    assert "row.voice_seconds_in = (row.voice_seconds_in or 0) + voice_seconds_in" in pipe
