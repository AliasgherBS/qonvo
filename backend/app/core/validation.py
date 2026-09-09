"""A 422 that reports the shape of a validation error, not its content (F10).

FastAPI's default 422 body carries pydantic's ``input`` key. For a
``value_error`` that is the offending field; for a ``missing`` error it is the
**whole submitted body**. So any single omitted field on a route that also
carries a secret returns that secret in full -- verified live before this
moved: ``POST /api/auth/signup`` with ``owner_name`` left out came back 422
with the new customer's plaintext password in the response body, on the very
first request they ever make, unauthenticated.

This started life inside ``app.api.config`` because that was the router known
to carry ``payment_details``. Three routers need it now (config, auth, team,
admin), and the reason it is still a route class rather than an app-wide
exception handler is unchanged: the ``detail``-is-a-list shape is a contract
every client reads, and making it app-wide would change all of them at once.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from fastapi import HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute


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


class QuietValidationRoute(APIRoute):
    """Routes whose 422 body reports the shape of the error, not the content.

    Done as a route class rather than an app-wide exception handler so it stays
    a property of this router: these are the endpoints that carry secrets, and
    a global change to the error format would be a change to every client's
    contract at once. The status code and the ``detail``-is-a-list shape are
    unchanged, so a dashboard reading ``detail[0].msg`` keeps working.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=quiet_errors(exc.errors()),
                ) from exc

        return handler
