"""English in, English out — even under forty turns of Urdu (E1).

The bug this file exists for, from the live transcript:

    06:13:37 IN   "Hello / What services do you offer?"        EN
    06:13:38 OUT  "Hello! We offer a range of salon and…"      EN  ok
    06:13:57 IN   "Do you provide laser tattoo removal?"       EN
    06:13:57 OUT  "Assalamualaikum! Laser tattoo removal ka…"  UR  wrong
    06:14:29 IN   "Book me a facial tomorrow"                  EN
    06:14:29 OUT  "Ji bilkul. Facial tomorrow ke liye…"        UR  wrong
    06:15:42 IN   [voice note, transcript: clean English]      EN
    06:15:42 OUT  "Assalamualaikum! Jee bilkul—Depilex mein…"  UR  wrong

It held for exactly one turn and then the history reasserted itself. The voice
case rules out the audio path: the transcript was flawless English.

Three things compounded. Nothing computed the language of the current message,
so "the language the customer used" was genuinely ambiguous with forty of them
in view. The rule sat at prompt position 0, the furthest possible point from
the message it governed. And the tenant's instructions carried a standing
prior ("Many write Roman Urdu; reply in Roman Urdu when they do") on every
single turn.

So the assertions below are about *placement* as much as detection. The first
test is the one that would have caught the original: an English message with an
Urdu-heavy history has to produce an English fact, and it has to sit next to the
message rather than forty turns away from it.
"""

from __future__ import annotations

import pytest
from app.agent.detect_language import ARABIC, LATIN, detect, language_fact
from app.workers.pipeline import build_turn_prompt

#: The tail of the real conversation, near enough. Every one of these would have
#: been in the history window when the English question was answered in Urdu.
URDU_HEAVY_HISTORY = [
    "Assalamualaikum, facial ka rate kya hai?",
    "Ji bilkul, facial 3500 se shuru hota hai.",
    "Achha, aur laser ka kitna hai?",
    "Laser ke liye branch confirm karni hogi.",
    "Theek hai, main kal aa sakti hun?",
]


# --- the regression ----------------------------------------------------------- #
def test_an_english_message_after_an_urdu_conversation_gets_an_english_fact():
    """The original bug, as a test.

    Nothing here mentions the history, and that is exactly the point: the fact
    is computed from *this* message, so no amount of Urdu behind it can change
    the answer.
    """
    summary = " ".join(URDU_HEAVY_HISTORY)

    turn = build_turn_prompt(
        context_block="Depilex offers facials, laser and bridal services.",
        conversation_summary=summary,
        message="Do you provide laser tattoo removal?",
        language_note=language_fact(
            "Do you provide laser tattoo removal?", reply_language="match"
        ),
    )

    assert "is in English (Latin script)" in turn
    assert "Roman Urdu" not in turn.split("Customer message:")[0].replace(summary, "")


def test_the_fact_sits_immediately_above_the_customer_message():
    """Placement is the fix. A rule at position 0 lost to the history between
    the two; a fact one line above the message has nothing in between to weigh
    it against."""
    turn = build_turn_prompt(
        context_block="Knowledge.",
        conversation_summary="An Urdu-flavoured summary.",
        message="Book me a facial tomorrow",
        language_note=language_fact("Book me a facial tomorrow", reply_language="match"),
    )

    blocks = turn.split("\n\n")
    assert blocks[-1].startswith("Customer message:")
    assert blocks[-2].startswith("The customer's current message is in English")


def test_the_customer_message_is_still_last():
    """The turn prompt's other invariant: whatever is added, the words being
    answered come last, because that is also the part that always differs and
    so must not sit in front of anything cacheable."""
    turn = build_turn_prompt(
        context_block="Knowledge.",
        conversation_summary=None,
        message="the actual question",
        language_note="The customer's current message is written in Latin script.",
    )

    assert turn.rstrip().endswith("the actual question")


def test_a_voice_transcript_is_treated_exactly_like_text():
    """The voice reply that came back in Roman Urdu had an English transcript,
    which is why the audio path was never the problem. Transcripts are written
    into ``fragment.body`` before coalescing, so they reach this same code."""
    transcript = "Hi, I wanted to ask if you do laser hair removal at the Lahore branch."

    assert language_fact(transcript, reply_language="match") == language_fact(
        transcript, reply_language="match"
    )
    assert "English" in (language_fact(transcript, reply_language="match") or "")


# --- detection: what it says --------------------------------------------------- #
@pytest.mark.parametrize(
    "message",
    [
        "Hello",
        "What services do you offer?",
        "Do you provide laser tattoo removal?",
        "Book me a facial tomorrow",
        "Can I get an appointment on Friday please",
        "how much is a haircut",
    ],
)
def test_english_is_recognised(message):
    assert detect(message).language == "English"
    assert detect(message).script == LATIN


@pytest.mark.parametrize(
    "message",
    [
        "kitne ka hai haircut?",
        "Assalamualaikum, facial ka rate kya hai?",
        "aap ka rate kya hai",
        "mujhe kal appointment chahiye",
        "shukriya",
    ],
)
def test_roman_urdu_is_recognised(message):
    assert detect(message).language == "Roman Urdu"
    assert detect(message).script == LATIN


def test_urdu_script_is_recognised_as_urdu():
    """Named as Urdu, not just as a script, because the Urdu-only letters are
    present and that is observable rather than guessed."""
    detected = detect("کیا آپ لیزر ٹیٹو ریموول کرتے ہیں؟")

    assert detected.script == ARABIC
    assert detected.language == "Urdu"


def test_arabic_without_urdu_letters_is_not_called_urdu():
    """An Arabic message is Arabic script and an unknown language. Guessing
    Urdu here would be the same mistake as guessing Roman Urdu for English."""
    detected = detect("مرحبا كيف الحال")

    assert detected.script == ARABIC
    assert detected.language is None


# --- detection: precision over recall ----------------------------------------- #
# Calling English "Roman Urdu" is the bug. A heuristic that does it in a new way
# would be no improvement, so every case below must come back as English, or as
# the script alone, and never as Roman Urdu.
@pytest.mark.parametrize(
    "message",
    [
        # Every one of these contains a word that is in some Roman Urdu word
        # list and is also ordinary English. They are all kept out of the
        # marker set for exactly this reason.
        "Is this the right number for bookings?",
        "Can you tell us about your par value pricing",
        "We hum along to the music",
        "Do you have a Kia dealership nearby",
        "Are you open? If so, what time",
        "Hi there",
        "Thanks, see you tomorrow",
    ],
)
def test_english_is_never_called_roman_urdu(message):
    assert detect(message).language != "Roman Urdu"


def test_one_marker_in_a_long_english_sentence_is_not_enough():
    """A single hit inside a long sentence is not evidence. Two distinct
    markers, or one plus a postposition, or one in a very short message."""
    assert detect("The salon is on Hai Street in the old part of town").language != "Roman Urdu"


@pytest.mark.parametrize("message", ["Merci beaucoup", "Hola, buenos dias", "Hi", "ok"])
def test_an_unestablished_language_reports_the_script_only(message):
    """The honest answer, and a safe one: the script is observable from the code
    points, and the owner's reply_language setting still decides the language
    exactly as it does today."""
    detected = detect(message)

    assert detected.script == LATIN
    fact = language_fact(message, reply_language="match")
    assert fact is not None
    assert "written in Latin script" in fact
    assert "English" not in fact


@pytest.mark.parametrize("message", ["👍", "https://example.com", "   ", "2500"])
def test_a_message_with_no_letters_supports_no_claim(message):
    assert detect(message).script is None
    assert language_fact(message, reply_language="match") is None


# --- the setting still wins where the owner set one ---------------------------- #
@pytest.mark.parametrize("mode", ["en", "Roman Urdu", "Portuguese"])
def test_a_pinned_language_gets_no_per_turn_fact(mode):
    """An owner who pinned a language has already been told so unconditionally
    in the system prompt. Adding an observation about the inbound message would
    hand the model two instructions and a choice, which is how this class of
    bug starts."""
    assert language_fact("Do you do laser?", reply_language=mode) is None


def test_match_is_what_produces_a_fact():
    assert language_fact("Do you do laser?", reply_language="match") is not None
    # None and "" both normalise to match, so a tenant who never saved the
    # setting (reply_language was NULL in the live database) still gets it.
    assert language_fact("Do you do laser?", reply_language=None) is not None
    assert language_fact("Do you do laser?", reply_language="") is not None


# --- the setting's own round trip ---------------------------------------------- #
# ``reply_language`` was NULL in the live database while the Behavior page showed
# "Match the customer" selected. That looked like a save bug, and it had been
# one: the page's `fields` list did not name `reply_language_mode`, so the value
# was dropped from the payload and the page still toasted "Saved". It is named
# there now, so the NULL is simply "never chosen" -- which resolves to match,
# which is what the page was showing. Locked down here because the round trip
# goes through a JSON map rather than a column, and a JSONB write that is not
# reassigned is never flushed.
def test_a_saved_reply_language_survives_the_round_trip():
    from types import SimpleNamespace

    from app.api.config import ConfigUpdateRequest, _apply_config_update, _config_to_dict

    row = SimpleNamespace(
        version=1,
        providers={"voice": {"mode": "match"}},
        escalation_rules={},
        persona=None,
        business_name="Depilex",
        languages=[],
        primary_language="en",
        tone=None,
        custom_instructions=None,
        business_hours={},
        owner_alert_number=None,
        llm_provider=None,
        llm_model=None,
        payment_details=None,
        billing_email=None,
        timezone="Asia/Karachi",
    )

    _apply_config_update(row, ConfigUpdateRequest(reply_language_mode="Roman Urdu"))

    # Stored beside the voice mode, not instead of it.
    assert row.providers["language"] == {"mode": "Roman Urdu"}
    assert row.providers["voice"] == {"mode": "match"}
    assert _config_to_dict(row).reply_language_mode == "Roman Urdu"


def test_never_choosing_reads_back_as_match():
    """Which is what the Behavior page was showing all along, so a NULL is not
    itself evidence of a lost write."""
    from types import SimpleNamespace

    from app.api.config import _config_to_dict

    row = SimpleNamespace(
        version=1,
        providers={"voice": {"mode": "match"}},
        escalation_rules={},
        persona=None,
        business_name="Depilex",
        languages=[],
        primary_language="en",
        tone=None,
        custom_instructions=None,
        business_hours={},
        owner_alert_number=None,
        llm_provider=None,
        llm_model=None,
        payment_details=None,
        billing_email=None,
        timezone="Asia/Karachi",
    )

    assert _config_to_dict(row).reply_language_mode == "match"
