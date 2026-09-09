""""Hi" is not a knowledge gap (F9).

A gap was logged whenever retrieval came back empty, and the top entry in the
owner's report was ``Hi``, twice, above a real refund complaint. The analytics
tile then advertised it under an "Answer these in Knowledge" call to action, so
the most valuable feedback loop in the product was telling a salon owner to go
and write a knowledge article about hello.

"Hi" retrieves nothing because there is nothing to retrieve, not because the
knowledge is missing. So the gate is intent rather than retrieval.

The bias is towards logging. A polluted report is annoying; a lost signal is
invisible, and this list is how an owner learns what their knowledge does not
cover. Anything with a single unrecognised word therefore counts as a question.
"""

from __future__ import annotations

import pytest
from app.agent.intent import has_informational_intent


@pytest.mark.parametrize(
    "message",
    [
        "Hi",
        "hi",
        "Hii",
        "Hello",
        "hey",
        "Good morning",
        "Assalamualaikum",
        "salam",
        "شکریہ",
        "thanks",
        "Thank you",
        "shukriya",
        "ok",
        "okay",
        "Bye",
        "yes",
        "no",
        "Hi 👋",
        "thanks!!!",
        "👍",
        "?",
        "",
    ],
)
def test_a_pleasantry_is_not_a_knowledge_gap(message):
    assert has_informational_intent(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "Hi, do you do laser?",
        "What services do you offer?",
        "Hello, kitna hai facial ka?",
        "thanks but I still want a refund",
        "کیا آپ لیزر کرتے ہیں",
        "refund kab milega",
        # Unrecognised words: a greeting in a language the set does not list is
        # far more likely to be a real question, so it is logged.
        "Bonjour, avez-vous des disponibilites",
        "price",
    ],
)
def test_a_real_question_is_still_logged(message):
    assert has_informational_intent(message) is True


def test_a_long_message_is_always_a_question():
    """Past a handful of words it is a message that happens to open politely,
    and whatever else it contains deserves to be counted."""
    assert has_informational_intent("hi hello hi hello hi hello hi") is True


def test_the_gate_is_wired_into_the_pipeline():
    """The gap is written in ``_run_pipeline_inner`` when retrieval is empty.
    Asserting the call site here so the helper cannot quietly stop being used:
    a pure function nobody calls is the same bug with more tests."""
    import inspect

    from app.workers import pipeline

    source = inspect.getsource(pipeline._run_pipeline_inner)
    assert "has_informational_intent(coalesced)" in source
    assert 'event_type="knowledge_gap"' in source
