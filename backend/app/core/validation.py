"""A 422 that reports the shape of a validation error, not its content (F10).

FastAPI's default 422 body carries pydantic's ``input`` key. For a
``value_error`` that is the offending field; for a ``missing`` error it is the
**whole submitted body**. So any single omitted field on a route that also
carries a secret returns that secret in full -- verified live before this
moved: ``POST /api/auth/signup`` with ``owner_name`` left out came back 422
with the new customer's plaintext password in the response body, on the very
first request they ever make, unauthenticated.

This started life inside ``app.api.config``, as a route class on the one
router known to carry ``payment_details``, on the reasoning that the
``detail``-is-a-list shape is a contract every client reads and a global
change would change all of them at once. Both halves of that were wrong.

The shape is not what changes -- ``quiet_errors`` preserves the status code and
the list, and drops only ``input`` and ``ctx``, which no client reads
(dashboard/lib/api.ts reads ``detail[0].msg`` and nothing else). And a curated
list of routers only ever covers the routers somebody thought of: four were
missed and found by asking the property of the route table, and a fifth was
found by tripping over it. So the handler is installed app-wide in
``app.main`` and this module is just the transformation.
"""

from __future__ import annotations

from collections.abc import Sequence


def quiet_errors(errors: Sequence[dict]) -> list[dict]:
    """A validation error report with the rejected value removed.

    FastAPI's default 422 body carries pydantic's ``input`` key, which is the
    whole of what was rejected. A 2,500-character instruction set came back in
    full, and this router also accepts ``payment_details`` -- the account
    number the rep reads out to customers -- so the echo puts a bank account
    into an error body, a browser console, an access log and anything that
    aggregates them.

    Nothing needs the value: the caller already has it, and
    :func:`app.core.limits.exceeded` deliberately puts the limit *and* the
    actual length into ``msg`` so the message is still actionable ("limited to
    2,000 characters. This is 3,140."). ``ctx`` goes too: pydantic puts the
    offending value in there for several built-in error types.
    """
    return [
        {k: v for k, v in error.items() if k not in ("input", "ctx", "url")} for error in errors
    ]
