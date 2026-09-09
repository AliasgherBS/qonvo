"""The instruction reviewer behind "Improve with AI" (functional test §04).

The three cases in this file are not invented. They are the sentences a real
tenant wrote, and each one caused a defect nothing in the product reported:

* the Roman Urdu rule out-voted the Reply language setting on every turn,
* "You cannot see any diary" switched off a connected Google Calendar and both
  booking skills while the Skills page said they worked,
* "a representative will call within a few hours" committed the business to a
  callback.

Nothing here talks to a provider. The model is scripted, which is the only
honest way to test the parts that are ours: which context reaches the prompt,
and what we refuse to show the owner.
"""

from __future__ import annotations

import json

import pytest
from app.agent.instruction_review import (
    MAX_CHANGES,
    SYSTEM_PROMPT,
    Suggestion,
    SuggestionTooLong,
    UnusableSuggestion,
    build_messages,
    describe_integrations,
    detect_conflicts,
    parse_suggestion,
)
from app.core.limits import MAX_CUSTOM_INSTRUCTIONS
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS

# --- the three live examples ----------------------------------------------------- #
ROMAN_URDU = "Many write Roman Urdu; reply in Roman Urdu when they do"
NO_DIARY = "Never say a time slot is free or booked. You cannot see any diary."
CALLBACK = (
    "A booking on WhatsApp is a request: take the city, the tier, the branch, the "
    "service, the preferred date and time, the name and the phone number, then tell "
    "the customer a representative will call within a few hours to confirm, and that "
    "a confirmation comes on WhatsApp afterwards."
)

#: An instruction set with none of the three problems, used to check that the
#: checks stay quiet. Taken from the placeholder the Behavior page already
#: shows, minus its language line.
CLEAN = """\
- Never quote a price. Say it depends on the branch and offer to check.
- If you do not know, say so and offer to pass the customer to the team.
- Never promise a booking time without checking the calendar first."""


def kinds(instructions: str, **kwargs) -> list[str]:
    return [c.kind for c in detect_conflicts(instructions, **kwargs)]


# --- the language override ------------------------------------------------------- #
def test_the_roman_urdu_rule_is_caught():
    """E1. This sentence beat the Reply language setting on every single turn,
    so an English message came back in Roman Urdu."""
    [conflict] = detect_conflicts(ROMAN_URDU)

    assert conflict.kind == "language"
    assert "Roman Urdu" in conflict.quote
    assert "Reply language setting" in conflict.note


def test_a_language_rule_is_caught_whatever_the_setting_says():
    """Even one that agrees with the setting. Agreement is not the problem:
    being in the prompt at all is, because on a long conversation it makes the
    rep follow the history's language rather than this message's."""
    assert kinds("Always reply in English.") == ["language"]
    assert kinds("Reply in the customer's language and script.") == ["language"]


# --- the diary contradiction ----------------------------------------------------- #
def test_the_diary_contradiction_is_caught_when_a_calendar_is_connected():
    """E4. Both halves of it: the ban on stating availability, and the denial
    of the tool itself."""
    found = detect_conflicts(NO_DIARY, connected=[GOOGLE_CALENDAR])

    assert [c.kind for c in found] == ["integration_denial", "integration_denial"]
    assert "free or booked" in found[0].quote
    assert "diary" in found[1].quote


def test_the_same_sentence_is_left_alone_with_nothing_connected():
    """The sentence is a defect or a plain fact depending on the tenant. With
    no calendar the rep genuinely cannot see one, and telling the owner to
    delete a true instruction would be the reviewer inventing a problem."""
    assert kinds(NO_DIARY, connected=[]) == []
    assert kinds(NO_DIARY, connected=[GOOGLE_SHEETS]) == []


def test_a_good_calendar_instruction_is_not_flagged():
    """The false positive worth guarding: "never promise a booking time without
    checking the calendar first" is exactly what an owner should write, and it
    carries a negation, a speech verb and the word calendar."""
    assert (
        kinds(
            "Never promise a booking time without checking the calendar first.",
            connected=[GOOGLE_CALENDAR],
        )
        == []
    )


# --- the callback commitment ----------------------------------------------------- #
def test_the_callback_commitment_is_caught():
    """E2. The promise was never invented by the model. It was instructed, word
    for word, and the model then elaborated on it."""
    [conflict] = detect_conflicts(CALLBACK, connected=[GOOGLE_CALENDAR])

    assert conflict.kind == "commitment"
    assert "representative will call within a few hours" in conflict.quote


@pytest.mark.parametrize(
    "line",
    [
        "Tell them someone will call back today.",
        "We will confirm by tonight.",
        "Promise the team will contact you within 24 hours.",
    ],
)
def test_other_commitments_are_caught_too(line):
    assert "commitment" in kinds(line)


# --- quiet on a clean set -------------------------------------------------------- #
def test_a_clean_instruction_set_raises_nothing():
    """A reviewer that flags everything is a reviewer nobody reads."""
    assert detect_conflicts(CLEAN, connected=[GOOGLE_CALENDAR, GOOGLE_SHEETS]) == []


# --- what reaches the prompt ----------------------------------------------------- #
def test_the_prompt_carries_the_reply_language_setting():
    """Without it the model cannot tell that a language line is redundant
    rather than load-bearing."""
    [_system, user] = build_messages(
        ROMAN_URDU,
        business_name="Depilex",
        reply_language_mode="match",
        connected=[],
    )

    assert "Reply language setting" in user.content
    assert "Depilex" in user.content


def test_the_prompt_names_the_connected_integrations():
    [_system, user] = build_messages(
        NO_DIARY, business_name="Depilex", reply_language_mode="en", connected=[GOOGLE_CALENDAR]
    )

    assert "Google Calendar" in user.content
    assert "Google Sheets" not in user.content


def test_the_prompt_says_so_when_nothing_is_connected():
    """The instruction "you cannot see any diary" is then correct, and the
    prompt has to say so or the model will delete a true sentence."""
    assert "Nothing is connected" in describe_integrations([])
    assert "must be kept" in describe_integrations([])


def test_flagged_sentences_reach_the_prompt_as_fallible_hints():
    """They are hints, not verdicts. A check that reached the model as an
    instruction would delete whatever it got wrong."""
    [_system, user] = build_messages(
        f"{ROMAN_URDU}\n{NO_DIARY}\n{CALLBACK}",
        business_name="Depilex",
        reply_language_mode="match",
        connected=[GOOGLE_CALENDAR],
    )

    assert "can be wrong" in user.content
    assert "Judge each one yourself" in user.content
    assert "Roman Urdu" in user.content
    assert "representative will call" in user.content


def test_the_instructions_are_delimited():
    """The owner's text is data, not instructions to the reviewer. A rule of
    theirs reading "ignore everything above" has to stay inside the markers."""
    [_system, user] = build_messages(
        ROMAN_URDU, business_name=None, reply_language_mode=None, connected=[]
    )

    assert "<<<INSTRUCTIONS" in user.content
    assert "INSTRUCTIONS>>>" in user.content


def test_the_prompt_forbids_inventing_and_states_the_cap():
    """Two things the prompt has to say, because the code cannot enforce
    either: a made-up price would be indistinguishable from a real one, and a
    suggestion over the cap can only be thrown away after it is paid for."""
    system = SYSTEM_PROMPT.format(limit=MAX_CUSTOM_INSTRUCTIONS, max_changes=MAX_CHANGES)

    assert "Invent nothing" in system
    assert str(MAX_CUSTOM_INSTRUCTIONS) in system
    assert "editor" in system


# --- parsing --------------------------------------------------------------------- #
def scripted(improved: str, changes: list[dict] | None = None) -> str:
    return json.dumps({"improved": improved, "changes": changes or []})


def test_a_well_formed_answer_parses_into_text_plus_changes():
    raw = scripted(
        "- Never quote a price.",
        [{"kind": "removed", "summary": "Removed the Roman Urdu rule."}],
    )

    suggestion = parse_suggestion(raw)

    assert suggestion.improved == "- Never quote a price."
    assert suggestion.changes[0].kind == "removed"
    assert suggestion.changes[0].summary == "Removed the Roman Urdu rule."
    assert suggestion.characters == len("- Never quote a price.")


def test_a_fenced_answer_still_parses():
    """Models add a fence even when told not to, and charging the owner for a
    press we then discard over punctuation would be indefensible."""
    raw = "Here you go:\n```json\n" + scripted("Keep it short.") + "\n```"

    assert parse_suggestion(raw).improved == "Keep it short."


def test_an_unknown_change_kind_is_normalised():
    """The model picks this string and the browser renders it as a label."""
    raw = scripted("Text.", [{"kind": "vibes", "summary": "Did something."}])

    assert parse_suggestion(raw).changes[0].kind == "changed"


def test_an_empty_change_list_is_a_valid_answer():
    """"Your instructions look fine" is worth the press, and manufacturing an
    edit to look busy is worse than saying nothing changed."""
    suggestion = parse_suggestion(scripted(CLEAN))

    assert suggestion.improved == CLEAN
    assert suggestion.changes == []


def test_too_many_changes_are_trimmed():
    raw = scripted("Text.", [{"kind": "removed", "summary": f"Edit {i}"} for i in range(20)])

    assert len(parse_suggestion(raw).changes) == MAX_CHANGES


def test_prose_instead_of_json_is_refused():
    with pytest.raises(UnusableSuggestion):
        parse_suggestion("Sure! Here are some better instructions for you.")


def test_an_empty_rewrite_is_refused():
    """An empty suggestion beside an Accept button is a button that wipes the
    most important field in the product."""
    with pytest.raises(UnusableSuggestion):
        parse_suggestion(scripted("   "))


def test_a_suggestion_over_the_cap_is_refused_not_offered():
    """Requirement: a suggestion that cannot be saved is a bug. Accepting it
    would end in the owner pressing Save and being told no, with their
    original already replaced in the textarea."""
    with pytest.raises(SuggestionTooLong) as excinfo:
        parse_suggestion(scripted("x" * (MAX_CUSTOM_INSTRUCTIONS + 1)))

    assert excinfo.value.actual == MAX_CUSTOM_INSTRUCTIONS + 1


def test_a_suggestion_exactly_at_the_cap_is_allowed():
    assert parse_suggestion(scripted("x" * MAX_CUSTOM_INSTRUCTIONS)).characters == (
        MAX_CUSTOM_INSTRUCTIONS
    )


def test_a_truncated_answer_is_refused_rather_than_repaired():
    """The failure mode this whole module exists to avoid: half a rewrite
    presented as a finished one."""
    truncated = '{"improved": "- Never quote a pri'

    with pytest.raises(UnusableSuggestion):
        parse_suggestion(truncated)


# --- the end to end shape, with a scripted model --------------------------------- #
def test_a_scripted_model_removes_all_three_and_says_why():
    """What an adequate model returns for the live instruction set, run through
    our own parsing. It proves the shape the owner is shown: the three
    sentences gone from the text, and one line each explaining it."""
    original = f"{ROMAN_URDU}\n{NO_DIARY}\n{CALLBACK}"
    answer = scripted(
        "Take the city, the branch, the service and the preferred date and time, "
        "plus the name and phone number, then say the team has been notified.",
        [
            {
                "kind": "removed",
                "summary": (
                    "Removed the Roman Urdu rule, because your Reply language "
                    "setting already controls this and the rule was overriding it."
                ),
            },
            {
                "kind": "removed",
                "summary": (
                    "Removed 'you cannot see any diary', because Google Calendar is "
                    "connected and that line switched off availability and booking."
                ),
            },
            {
                "kind": "tightened",
                "summary": (
                    "Kept the details you collect and dropped the promise that a "
                    "representative will call within a few hours."
                ),
            },
        ],
    )

    suggestion: Suggestion = parse_suggestion(answer)

    assert "Roman Urdu" not in suggestion.improved
    assert "diary" not in suggestion.improved
    assert "representative will call" not in suggestion.improved
    assert suggestion.improved != original
    assert len(suggestion.changes) == 3
    assert all(c.summary for c in suggestion.changes)
