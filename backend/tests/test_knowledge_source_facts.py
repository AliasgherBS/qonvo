"""What a source row can say about itself (teardown K2).

A source was a name, a type and a date. How much of it the rep actually holds,
how big the upload behind it was and when a website was last crawled were all
either measured elsewhere or not at all, so a URL that went stale six weeks ago
rendered identically to one fetched this morning.

These are unit tests over the response mapping, which is where a measured fact
gets dropped on the way to the page.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.api.knowledge import _to_response
from app.api.knowledge_limits import SourceStats
from app.models.enums import KnowledgeSourceType

CREATED = dt.datetime(2026, 9, 1, 9, 30, tzinfo=dt.UTC)
CRAWLED = dt.datetime(2026, 9, 7, 18, 5, tzinfo=dt.UTC)


def _row(**overrides):
    base = {
        "id": uuid.uuid4(),
        "type": KnowledgeSourceType.website,
        "name": "Our FAQ page",
        "url": "https://example.com/faq",
        "content": None,
        "status": "ready",
        "auto_refresh": False,
        "created_at": CREATED,
        "last_ingested_at": CRAWLED,
        "meta": {},
    }
    return SimpleNamespace(**{**base, **overrides})


def test_a_website_reports_when_it_was_last_crawled():
    assert _to_response(_row()).last_ingested_at == CRAWLED


def test_a_source_that_has_never_finished_ingesting_says_so():
    """None, not the created date. "Last crawled" showing the moment the row was
    added would describe a fetch that never happened."""
    assert _to_response(_row(last_ingested_at=None)).last_ingested_at is None


def test_stored_size_comes_from_the_chunks_that_exist():
    out = _to_response(_row(), SourceStats(chars=7775, chunks=9))
    assert (out.chars, out.chunks) == (7775, 9)


def test_a_source_with_no_chunks_reports_zero_rather_than_failing():
    """A source still being fetched has no stats row at all, and the list is
    rendered for every source or none."""
    out = _to_response(_row(status="pending_ingest"), None)
    assert (out.chars, out.chunks) == (0, 0)


def test_an_uploaded_file_reports_its_size():
    out = _to_response(
        _row(
            type=KnowledgeSourceType.file,
            url=None,
            meta={"upload_path": "/data/x.pdf", "upload_bytes": 1_468_006},
        )
    )
    assert out.upload_bytes == 1_468_006


def test_a_source_that_was_never_uploaded_has_no_size():
    """None rather than 0: a manual entry has no file, and "0 B" is a claim
    about a file that does not exist."""
    assert _to_response(_row()).upload_bytes is None


def test_a_junk_upload_size_is_reported_as_unknown():
    """`meta` is a free-form JSON column. Coercing whatever is in there would
    turn somebody else's data into a number on the owner's screen."""
    assert _to_response(_row(meta={"upload_bytes": "quite big"})).upload_bytes is None
