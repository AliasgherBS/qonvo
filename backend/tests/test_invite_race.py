"""H2 from the VPS audit: a double-click on "Send invite" broke the seat cap.

Two identical invitations fired concurrently both returned 201, and a two-seat
plan reported "used 3 of 2". The gate then correctly refused the next one, so
the damage caps at one seat per race -- but on a fifteen-seat plan it repeats,
and a double submit is exactly this shape.

The handler counts seats, then inserts. A second request can pass the same
count before either has written, and no amount of care between those two
statements closes a window that exists because they are two statements. Only a
constraint the database evaluates at write time does, which is migration 0016.

These tests pin the rule the index encodes, since the index itself is only
exercised against a real Postgres (tests/test_migrations, -m postgres).
"""

from __future__ import annotations

import pathlib
import re

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app/alembic/versions/0016_one_pending_invite.py"
)


def _sql() -> str:
    return MIGRATION.read_text()


def test_the_index_is_partial_on_pending():
    """An address invited, accepted, then invited again is ordinary. Only one
    LIVE invitation per address is the rule -- a total unique index would
    forbid the normal case."""
    sql = _sql()
    assert "WHERE status = 'pending'" in sql


def test_the_index_is_case_insensitive():
    """Alice@example.com and alice@example.com are one mailbox, and a race does
    not care about capitalisation."""
    assert "lower(email)" in _sql()


def test_duplicates_are_revoked_not_deleted():
    """A migration that deletes rows to make an index fit loses the evidence
    that an invitation was ever sent."""
    sql = _sql()
    assert "SET status = 'revoked'" in sql
    assert "DELETE FROM team_invitations" not in sql.upper()


def test_the_index_creation_is_guarded():
    """0001 builds the schema with create_all from the current models, so a
    later unguarded DDL collides on any database that already has the object."""
    assert "get_indexes" in _sql()


def test_the_revision_id_fits_the_version_column():
    """alembic_version.version_num is varchar(32). A longer id fails at the very
    last statement of the migration, after the work is done."""
    m = re.search(r'^revision: str = "([^"]+)"', _sql(), re.M)
    assert m and len(m.group(1)) <= 32


def test_the_handler_turns_the_violation_into_a_409():
    """Without this the loser of the race gets a 500, which reads as "the
    product is broken" rather than "that person is already invited"."""
    team = (pathlib.Path(__file__).resolve().parents[1] / "app/api/team.py").read_text()
    assert "IntegrityError" in team
    assert "already pending" in team
