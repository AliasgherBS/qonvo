"""H1 and M2 from the VPS audit (2026-09-11).

H1 is the same defect found twice. A NUL byte is legal in a Python str and
illegal in a Postgres text column, so it survives every layer until the INSERT.
The first review found it as a worker crash that left a real 391 KB PDF on
"Processing" for ever. That was fixed on the *file* path -- and the next review
found the identical byte arriving through the JSON API instead, now as a 500.

Fixing a parser fixed one door in a room with two. These tests pin the fix to
the request model, which is the boundary every entry point crosses.
"""

from __future__ import annotations

import pytest
from app.api.knowledge import CreateSourceRequest, UpdateSourceRequest
from pydantic import ValidationError


@pytest.mark.parametrize("field", ["title", "content"])
def test_create_strips_the_nul_byte(field):
    kw = {"type": "manual", "title": "ok", "content": "ok"}
    kw[field] = "before\x00after"
    assert "\x00" not in getattr(CreateSourceRequest(**kw), field)


@pytest.mark.parametrize("field", ["title", "content"])
def test_update_strips_it_too(field):
    """The edit path is a second door: sanitising only the create would leave a
    NUL reachable by editing an existing source."""
    assert "\x00" not in getattr(UpdateSourceRequest(**{field: "a\x00b"}), field)


def test_nul_becomes_a_space_not_a_join():
    """Deleting it would invent a word that was never there -- a NUL in a PDF
    text layer is usually where a glyph should have been."""
    r = CreateSourceRequest(type="manual", title="t", content="before\x00after")
    assert r.content == "before after"


def test_a_lone_surrogate_does_not_survive_either():
    r = CreateSourceRequest(type="manual", title="t", content="bad \ud800 here")
    r.content.encode("utf-8")  # would raise before the fix


def test_real_text_is_untouched():
    """The sanitiser must not be a unicode filter: Arabic, CJK and emoji are
    ordinary content for this product."""
    text = "سلام 😀 中文 — naïve"
    assert CreateSourceRequest(type="manual", title=text, content=text).content == text


def test_an_empty_title_is_refused():
    """M2: it returned 201 and rendered a blank row nobody could identify.
    `content` had a length rule; `title` had only "required"."""
    with pytest.raises(ValidationError):
        CreateSourceRequest(type="manual", title="", content="x")


def test_a_title_is_still_required_to_be_sane_on_update():
    with pytest.raises(ValidationError):
        UpdateSourceRequest(title="")
