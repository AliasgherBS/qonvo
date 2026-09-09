"""Answering a knowledge gap closes the loop (teardown K1).

The product already knew what it had failed to answer and showed it to the
owner, and there was nothing to do about it from there. Answering a gap now
writes a knowledge entry *and* a marker event, and the gap list excludes
questions that have one -- until the same question is asked again after the
answer was written, because then the answer did not work.

Tested here rather than against Postgres because the two things that can break
are the id parsing (a question containing a colon) and the exclusion clause
being built at all. Both are visible without a database.
"""

from __future__ import annotations

import uuid

import pytest
from app.api.knowledge import (
    GAP_ANSWERED_EVENT,
    CreateSourceRequest,
    UpdateSourceRequest,
    _gap_question,
    _mark_gap_answered,
    answered_gaps_subquery,
    gaps_query,
)
from sqlalchemy.dialects import postgresql


class _RecordingSession:
    """Just enough session to see what would be written."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


# --- the gap id ---------------------------------------------------------------- #
@pytest.mark.parametrize(
    "gap_id,expected",
    [
        ("knowledge_gap:do you deliver?", "do you deliver?"),
        ("escalation:can I pay on arrival?", "can I pay on arrival?"),
        # The question itself contains a colon. Splitting on the last one, or on
        # every one, would answer a gap that does not exist and leave the real
        # one on the list forever.
        ("knowledge_gap:open hours: sunday?", "open hours: sunday?"),
        # Not a prefixed id at all: taken as the whole question rather than
        # silently truncated to nothing.
        ("do you deliver?", "do you deliver?"),
        ("something_else:kept whole", "something_else:kept whole"),
    ],
)
def test_the_question_is_recovered_from_the_gap_id(gap_id: str, expected: str):
    assert _gap_question(gap_id) == expected


# --- the marker ---------------------------------------------------------------- #
def test_answering_a_gap_records_a_marker_against_the_question():
    db = _RecordingSession()
    tenant_id, source_id = uuid.uuid4(), uuid.uuid4()

    _mark_gap_answered(db, tenant_id, "knowledge_gap:do you deliver?", source_id=source_id)

    (event,) = db.added
    assert event.tenant_id == tenant_id
    assert event.event_type == GAP_ANSWERED_EVENT
    # The bare question, not the id: the same question asked with no knowledge
    # and asked with the wrong knowledge is one thing to answer, not two.
    assert event.data["question"] == "do you deliver?"
    assert event.data["source_id"] == str(source_id)
    assert event.occurred_at is not None


def test_the_marker_carries_the_source_that_answers_it():
    """A resolution with no source behind it would hide a question nobody
    answered, which is worse than the dead end it replaced."""
    db = _RecordingSession()
    source_id = uuid.uuid4()
    _mark_gap_answered(db, uuid.uuid4(), "escalation:refunds?", source_id=source_id)
    assert db.added[0].data["source_id"] == str(source_id)


# --- the exclusion ------------------------------------------------------------- #
def _compiled(stmt):
    return stmt.compile(dialect=postgresql.dialect())


def test_the_answered_subquery_looks_only_at_marker_events():
    compiled = _compiled(answered_gaps_subquery(uuid.uuid4()).select())
    assert GAP_ANSWERED_EVENT in compiled.params.values()


def test_the_gap_list_excludes_answered_questions():
    """The clause, asserted on the generated SQL. An outer join with a HAVING
    is either right or silently returns every row, and a page that lists gaps
    the owner has already answered is the dead end this was meant to fix."""
    sql = str(_compiled(gaps_query(uuid.uuid4(), 50)))
    assert "LEFT OUTER JOIN" in sql
    assert "answered_at IS NULL" in sql
    # The "asked again since" half: without it, answering a gap would hide the
    # question permanently even when the answer demonstrably did not work.
    assert "> anon_1.answered_at" in sql


def test_the_gap_list_still_asks_for_both_kinds_of_failure():
    """A retrieval miss and an escalation are both gaps. Narrowing this while
    adding the exclusion would silently halve the list."""
    params = _compiled(gaps_query(uuid.uuid4(), 50)).params
    kinds = next(v for v in params.values() if isinstance(v, list))
    assert set(kinds) == {"knowledge_gap", "escalation"}


# --- the request shapes -------------------------------------------------------- #
def test_a_source_can_be_created_without_answering_a_gap():
    body = CreateSourceRequest(type="manual", title="Refunds", content="14 days.")
    assert body.answers_gap_id is None


def test_answering_a_gap_is_part_of_the_create_not_a_second_call():
    """One call, so the gap cannot be marked answered while the entry that
    answers it failed to save."""
    body = CreateSourceRequest(
        type="manual",
        title="Do you deliver?",
        content="Question: do you deliver?\nAnswer: yes, within Lahore.",
        answers_gap_id="knowledge_gap:do you deliver?",
    )
    assert body.answers_gap_id == "knowledge_gap:do you deliver?"


def test_a_plain_edit_does_not_refetch():
    """`refetch` re-crawls a website and spends embedding money. It has to be
    asked for, never implied by a title change."""
    assert UpdateSourceRequest(title="New name").refetch is False
