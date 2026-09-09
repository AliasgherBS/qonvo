"""When the owner's instructions fight a connected integration (E4).

The live tenant had Google Calendar connected and passing its test, and
instructions reading "Never say a time slot is free or booked. You cannot see
any diary." The Skills page said "Check availability: reads your calendar
before offering a time" and "Available". The rep never called it once.

Two surfaces of the same product contradicted each other, neither knew, and the
owner's only route to finding out was reading a customer's transcript.

The decision made is that the connected integration wins. That is now told to
the model in the prompt (``pipeline.tool_authority``) *and* to the owner here,
because a fix the owner cannot see is a fix they cannot trust.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.agent.instruction_review import detect_conflicts
from app.api.config import CONFLICT_NOTICE, skill_states
from app.integrations import GOOGLE_CALENDAR

#: Verbatim from the live tenant.
DENIES_THE_DIARY = (
    "Never say a time slot is free or booked. You cannot see any diary. "
    "A booking on WhatsApp is a request."
)

CALENDAR_SKILLS = {
    "check_availability": SimpleNamespace(
        description="check availability",
        requires_integration=GOOGLE_CALENDAR,
        requires_config_key=None,
    ),
    "capture_lead": SimpleNamespace(
        description="capture a lead", requires_integration=None, requires_config_key=None
    ),
}


def _rows(*, ready, instructions):
    return {
        row.key: row
        for row in skill_states(
            CALENDAR_SKILLS,
            ready=ready,
            config_row=SimpleNamespace(),
            configured={},
            conflicts=detect_conflicts(instructions, connected=sorted(ready)),
        )
    }


def test_a_working_skill_the_instructions_deny_is_flagged():
    rows = _rows(ready={GOOGLE_CALENDAR}, instructions=DENIES_THE_DIARY)

    assert rows["check_availability"].available is True
    assert rows["check_availability"].conflict == CONFLICT_NOTICE
    # Two sentences in this instruction set qualify; the row carries the first,
    # because a row is one notice and an owner who fixes one will see the other.
    assert rows["check_availability"].conflict_quote in DENIES_THE_DIARY


def test_the_notice_says_which_one_wins():
    """The whole point. "There is a contradiction" leaves the owner where they
    started; "the integration wins, your rep will still use this" tells them
    what their product is actually doing."""
    assert "connected integration wins" in CONFLICT_NOTICE
    assert "will still use this skill" in CONFLICT_NOTICE


def test_the_notice_admits_to_being_a_heuristic():
    """A phrase list cannot understand someone's instructions, and saying it
    can would be a larger promise than it can keep. An owner told "this might
    be wrong" can judge for themselves; one told "this is wrong" and who
    disagrees has no move."""
    assert "keyword check" in CONFLICT_NOTICE
    assert "can be wrong" in CONFLICT_NOTICE


def test_the_owner_s_own_sentence_is_quoted_so_they_can_find_it():
    rows = _rows(ready={GOOGLE_CALENDAR}, instructions=DENIES_THE_DIARY)

    quote = rows["check_availability"].conflict_quote
    assert quote in DENIES_THE_DIARY


def test_nothing_is_flagged_when_the_integration_is_not_connected():
    """"You cannot see any diary" is honest for a tenant with no calendar, and
    a defect for a tenant with one. Same sentence, opposite verdict, so the
    check has to be gated on the connection."""
    rows = _rows(ready=set(), instructions=DENIES_THE_DIARY)

    assert rows["check_availability"].available is False
    assert rows["check_availability"].conflict is None


def test_an_ungated_skill_is_never_flagged_by_a_calendar_conflict():
    """The conflict is about an integration, so it attaches to the skills that
    need that integration and to nothing else."""
    rows = _rows(ready={GOOGLE_CALENDAR}, instructions=DENIES_THE_DIARY)

    assert rows["capture_lead"].conflict is None


def test_ordinary_instructions_are_left_alone():
    """A false positive costs an owner a confusing notice on a page they trust,
    so the quiet case has to stay quiet."""
    rows = _rows(
        ready={GOOGLE_CALENDAR},
        instructions="Be warm. Quote prices from the price list only. Branches: Lahore, Karachi.",
    )

    assert all(row.conflict is None for row in rows.values())


def test_no_instructions_at_all_is_not_a_conflict():
    rows = _rows(ready={GOOGLE_CALENDAR}, instructions="")

    assert all(row.conflict is None for row in rows.values())


def test_the_default_is_no_conflict_so_every_existing_caller_is_unaffected():
    """``conflicts`` defaults to empty: the admin console's own config surface
    calls this too, and a new keyword must not change what it renders."""
    rows = skill_states(
        CALENDAR_SKILLS, ready={GOOGLE_CALENDAR}, config_row=SimpleNamespace(), configured={}
    )

    assert all(row.conflict is None for row in rows)
