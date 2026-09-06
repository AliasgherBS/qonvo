"""Reply language is a setting, not a sentence in the prompt.

Voice already works this way: a validated mode with three options. Language had
no equivalent and was governed only by prose in custom_instructions, which is
why it drifts -- an Urdu-script question came back in Roman Urdu.

The critical property is that this is **script-aware**. Urdu and Roman Urdu are
one language in two scripts, and treating them as one setting is the exact
failure being fixed, so they are separate choices and "match" has to mean the
script too.
"""

from __future__ import annotations

import pytest
from app.agent.language import (
    SUPPORTED_REPLY_LANGUAGES,
    language_instruction,
    normalise_reply_language,
)


# --- the option set ----------------------------------------------------------- #
def test_match_is_the_default():
    assert normalise_reply_language(None) == "match"
    assert normalise_reply_language("") == "match"


def test_urdu_script_and_roman_urdu_are_separate_choices():
    """Conflating them is the bug. One language, two scripts, two options."""
    codes = {lang.code for lang in SUPPORTED_REPLY_LANGUAGES}

    assert "ur" in codes, "Urdu script"
    assert "ur-Latn" in codes, "Roman Urdu"


def test_english_is_offered_and_so_are_the_regional_languages():
    codes = {lang.code for lang in SUPPORTED_REPLY_LANGUAGES}

    assert {"match", "en", "ur", "ur-Latn"} <= codes
    # The market this is built for, per the product spec.
    assert {"pa", "pa-Latn", "sd", "ar"} <= codes


def test_every_option_has_a_label_a_human_can_pick_from():
    for lang in SUPPORTED_REPLY_LANGUAGES:
        assert lang.label.strip()
        assert lang.code.strip()


def test_an_unknown_code_falls_back_to_match_rather_than_failing():
    """A stale value from an older build must not break every reply."""
    assert normalise_reply_language("klingon") == "match"


# --- what the model is told ---------------------------------------------------- #
def test_match_tells_the_model_to_mirror_the_script_too():
    text = language_instruction("match").lower()

    assert "script" in text, "mirroring the language but not the script is the bug"


def test_a_fixed_language_is_stated_unconditionally():
    text = language_instruction("ur")

    assert "Urdu" in text
    assert "regardless" in text.lower() or "always" in text.lower()


def test_roman_urdu_names_the_script_explicitly():
    """"Reply in Urdu" to a model means Urdu script. Roman Urdu has to say so,
    or the setting silently does the wrong one of the two things it exists to
    distinguish."""
    text = language_instruction("ur-Latn")

    assert "Roman" in text or "Latin" in text
    assert "Urdu" in text


@pytest.mark.parametrize("code", [lang.code for lang in SUPPORTED_REPLY_LANGUAGES])
def test_every_supported_option_produces_an_instruction(code):
    assert language_instruction(code).strip()
