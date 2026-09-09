"""A dead job must not leave a row claiming to be in progress (F1, F2, F5).

A genuine 391 KB PDF sat on "Processing" for ever. The worker had died on
``CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8":
0x00`` while inserting knowledge chunks, and the handler that was supposed to
mark the source failed wrote to the *same* session the insert had just aborted.
So the status change was rolled back with everything else: no error, no retry,
no timeout, and an owner watching a spinner that would never stop.

Two separate defects, and the second is the general one. Stripping NUL bytes
fixes this file; a failure path that does not share a transaction with the
failure fixes the class.
"""

from __future__ import annotations

import pytest
from app.agent.ingestion import extract_text, sanitise_extracted_text


# --- the immediate cause --------------------------------------------------------- #
def test_a_nul_byte_is_removed():
    """0x00 is legal in a Python str and illegal in a Postgres text column, so
    it survives parsing, chunking and embedding and only fails at the INSERT."""
    assert "\x00" not in sanitise_extracted_text("Facial\x00 treatment\x00 Rs 5000")


def test_the_words_either_side_are_not_joined():
    """A NUL in a PDF text layer is usually where a glyph should have been.
    Deleting it invents a word that was never in the document."""
    assert sanitise_extracted_text("Facial\x00treatment") == "Facial treatment"


def test_a_lone_surrogate_is_removed():
    """Survives `str` and cannot be encoded to UTF-8 at all. PDF and DOCX
    extraction both produce them from broken glyph maps."""
    cleaned = sanitise_extracted_text("price\ud800list")

    assert cleaned.encode("utf-8")  # would raise before
    assert "\ud800" not in cleaned


@pytest.mark.parametrize(
    "text",
    [
        "Facial treatment Rs 5000",
        "فیشل ٹریٹمنٹ",  # Urdu, which must survive untouched
        "Rs 5,000 · 45 min",
        "",
    ],
)
def test_legitimate_text_is_untouched(text):
    """The sanitiser must not be a quiet mangler of every non-Latin script."""
    assert sanitise_extracted_text(text) == text


@pytest.mark.parametrize("kind", ["text", "markdown", "csv"])
def test_every_parser_output_is_sanitised(kind):
    """Applied in `extract_text` rather than in each parser, so a parser added
    later cannot forget. The failure is invisible in the parser, in the
    chunker, and everywhere before the insert."""
    assert "\x00" not in extract_text(source_type=kind, raw_text="a\x00b")


def test_the_url_path_is_sanitised_too():
    """A crawled page can carry a NUL just as a PDF can, and the URL path
    returns its own text rather than going through a parser."""
    import ast
    import inspect

    from app.agent import ingestion

    tree = ast.parse(inspect.getsource(ingestion.fetch_url_text).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")

    assert "sanitise_extracted_text" in ast.unparse(tree)


# --- the general cause, which is the one that matters ----------------------------- #
def test_the_failure_path_does_not_use_the_failed_session():
    """The whole bug. The handler set `source.status = "error"` on the session
    whose transaction the insert had just aborted, so the write was rolled back
    and the row kept saying `pending_ingest`.

    Asserted structurally because reproducing it needs a real Postgres and a
    real aborted transaction, and the property worth defending is that the
    handler never touches `db`.
    """
    import ast
    import inspect

    from app.workers import worker

    source = inspect.getsource(worker.ingest_knowledge_source)
    tree = ast.parse(source.lstrip())

    # The broad handler specifically. There is also an `except LimitExceeded`
    # in this function which *does* write through `db`, and correctly: a limit
    # refusal is raised by our own check before any database call, so the
    # session is healthy and the write lands. The one that must not is the
    # catch-all, because that is the one a DBAPIError arrives at with the
    # transaction already aborted.
    broad = [
        h
        for h in ast.walk(tree)
        if isinstance(h, ast.ExceptHandler)
        and isinstance(h.type, ast.Name)
        and h.type.id == "Exception"
    ]
    assert broad, "expected a catch-all handler on the ingest job"
    body = ast.unparse(broad[0])

    assert "_mark_source_failed" in body, "the failure must be recorded out of band"
    assert "source.status" not in body, (
        "the catch-all must not write through the session that failed"
    )


def test_marking_a_source_failed_never_raises():
    """It is already the error path. If even this cannot write, the log line is
    the record, and raising would replace one lost failure with another."""
    import ast
    import inspect

    from app.workers import worker

    tree = ast.parse(inspect.getsource(worker._mark_source_failed).lstrip())
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]

    assert handlers, "must swallow its own failure"
    assert not any(isinstance(n, ast.Raise) for h in handlers for n in ast.walk(h))


def test_the_reason_is_readable_rather_than_a_stack_trace():
    """The table read "Nothing indexed - Error" and the API carried no error
    field, so a corrupt file and a bad minute looked identical."""
    from app.workers.worker import _readable_ingest_error

    nul = _readable_ingest_error(
        Exception('CharacterNotInRepertoireError: invalid byte sequence for encoding "UTF8": 0x00')
    )

    assert "characters we could not store" in nul
    assert "0x00" not in nul, "an owner cannot act on a byte value"


def test_the_api_exposes_the_reason():
    from app.api.knowledge import SourceResponse

    assert "error" in SourceResponse.model_fields


# --- a lost customer message must tell somebody ---------------------------------- #
def test_a_dead_letter_row_notifies_the_owner():
    """Retry worked and the dead-letter row was written, and two customer
    messages still went unanswered for four days, because nothing reads that
    table. From the owner's side it looked like a customer going quiet."""
    import ast
    import inspect

    from app.workers import worker

    tree = ast.parse(inspect.getsource(worker._write_failed_job).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value = ast.Constant(value="")
    body = ast.unparse(tree)

    assert "FailedJob(" in body, "the row is still the durable record"
    assert "notify(" in body, "and somebody has to be told about it"


def test_a_quota_refusal_reads_as_something_the_owner_can_act_on():
    """Both real failures were HTTP 429 "exceeded your current quota". An owner
    can top up a provider account; they cannot act on a stack trace."""
    from app.workers.worker import _readable_job_error

    message = _readable_job_error(
        Exception('/chat/completions failed (429): {"error": {"code": 429, '
                  '"message": "You exceeded your current quota"}}')
    )

    assert "quota" in message
    assert "429" not in message


def test_the_notification_names_the_customer_the_way_the_inbox_does():
    """A notification calling somebody `923009998877@c.us` while the inbox
    calls them +92 300 999 8877 is two names for one person."""
    from app.workers.worker import _readable_chat

    assert _readable_chat("923009998877@c.us") == "+92 300 999 8877"
