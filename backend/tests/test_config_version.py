"""H4 from the VPS audit: two editors silently overwrote each other.

    tone before: "Warm, Concise, Direct"
    PUT {"tone":"RACE-AAA"}  -> 200
    PUT {"tone":"RACE-BBB"}  -> 200      (both accepted)
    tone after : "RACE-BBB"              last write wins, silently

Unlike the activation toggle, where "the last person to click wins" is what
anyone expects of a global boolean, configuration is long-form text somebody
wrote. Losing it behind a success message is the failure.

The fix has two halves and needs both. A read-time comparison catches a caller
whose copy was already stale when it arrived. `version_id_col` puts the same
assertion in the UPDATE's WHERE clause, which is what closes the window between
two simultaneous requests -- the comparison alone was tried first and both
requests still returned 200, because both read the same version before either
wrote.
"""

from __future__ import annotations

import pathlib

CONFIG_API = pathlib.Path(__file__).resolve().parents[1] / "app/api/config.py"
MODEL = pathlib.Path(__file__).resolve().parents[1] / "app/models/tenant.py"


def test_the_model_uses_native_optimistic_locking():
    """The half that survives concurrency: SQLAlchemy appends
    `AND version = :loaded` to the UPDATE, so the loser matches no row."""
    assert 'version_id_col' in MODEL.read_text()


def test_the_handler_also_checks_at_read_time():
    """The half that gives a good error for the common case: a caller whose
    copy went stale before they pressed save."""
    s = CONFIG_API.read_text()
    assert "body.version is not None and body.version != row.version" in s


def test_the_handler_never_assigns_the_version_itself():
    """SQLAlchemy owns that column. Assigning it by hand stops the guard
    working -- which is exactly how the first attempt passed its unit tests and
    failed the live race."""
    assert "row.version =" not in CONFIG_API.read_text()


def test_a_stale_write_is_a_409_not_a_500():
    s = CONFIG_API.read_text()
    assert "StaleDataError" in s
    assert "HTTP_409_CONFLICT" in s


def test_the_version_is_optional_on_the_way_in():
    """A client that does not send one keeps working, so shipping this cannot
    break a browser tab holding older JavaScript."""
    assert "version: int | None = None" in CONFIG_API.read_text()


def test_the_version_is_returned_so_a_client_can_send_it_back():
    s = CONFIG_API.read_text()
    assert "version: int" in s
    assert "version=row.version or 1" in s


def test_version_is_exempt_from_the_null_erasure_check():
    """It is metadata about the write, not content, so `{"version": null}` must
    not be read as an attempt to erase a field."""
    assert '{"version"}' in CONFIG_API.read_text()
