"""A rejection must not echo what it rejected (F10).

FastAPI's default 422 body carries pydantic's ``input`` key, which is the whole
of what was rejected. A 2,500-character instruction set came back in full, and
this router also accepts ``payment_details`` -- the receiving account the rep
reads out verbatim to customers -- so the echo puts a bank account into an
error body, a browser console, an access log, and anything that aggregates
them.

Nothing needs the value. The caller already has it, and
``app.core.limits.exceeded`` deliberately puts the limit *and* the actual
length into the message, so "limited to 1,000 characters. This is 2,500." is
still enough to act on without repeating a single digit of the account number.
"""

from __future__ import annotations

from app.api.config import quiet_errors
from app.core.limits import MAX_PAYMENT_DETAILS


def test_the_rejected_value_is_removed():
    secret = "Meezan Bank 0123456789012345, IBAN PK36SCBL0000001123456702"
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "payment_details"),
            "msg": "Payment details is limited to 1,000 characters. This is 2,500.",
            "input": secret,
            "url": "https://errors.pydantic.dev/2.9/v/value_error",
        }
    ]

    quiet = quiet_errors(errors)

    assert secret not in repr(quiet)
    assert "input" not in quiet[0]


def test_the_message_and_the_field_survive():
    """The owner still has to be able to act on it, and the dashboard reads
    ``detail[0].msg``."""
    quiet = quiet_errors(
        [
            {
                "type": "value_error",
                "loc": ("body", "custom_instructions"),
                "msg": "Custom instructions is limited to 2,000 characters. This is 3,140.",
                "input": "x" * 3_140,
            }
        ]
    )

    assert quiet[0]["loc"] == ("body", "custom_instructions")
    assert "2,000" in quiet[0]["msg"]
    assert "3,140" in quiet[0]["msg"]


def test_ctx_goes_too():
    """pydantic puts the offending value in ``ctx`` for several of its built-in
    error types, so stripping only ``input`` would leak on those."""
    quiet = quiet_errors(
        [{"type": "string_too_long", "loc": ("body", "x"), "msg": "too long",
          "input": "secret", "ctx": {"max_length": 10, "given": "secret"}}]
    )

    assert "secret" not in repr(quiet)
    assert "ctx" not in quiet[0]


def test_the_real_validator_still_reports_the_numbers_without_the_value():
    """End to end through the model that actually rejects it: the numbers come
    from ``exceeded``, and the value comes from nowhere."""
    import pydantic
    from app.api.config import ConfigUpdateRequest

    secret = "9" * (MAX_PAYMENT_DETAILS + 1)
    try:
        ConfigUpdateRequest(payment_details=secret)
    except pydantic.ValidationError as err:
        quiet = quiet_errors(err.errors())
    else:  # pragma: no cover - the cap is the point of the test
        raise AssertionError("an over-length value was accepted")

    assert secret not in repr(quiet)
    assert f"{MAX_PAYMENT_DETAILS:,}" in quiet[0]["msg"]
    assert f"{MAX_PAYMENT_DETAILS + 1:,}" in quiet[0]["msg"]


def test_the_handler_is_installed_app_wide():
    """Not on a router. A route class only ever covered the routers somebody
    thought of, which is how four routes and then a fifth were missed.

    Asserting *which* handler, not that one exists: FastAPI installs its own
    for this exception, so ``RequestValidationError in app.exception_handlers``
    is true whether ours is registered or not. The first version of this test
    asserted exactly that and passed with the handler removed.
    """
    from app.main import app
    from fastapi.exceptions import RequestValidationError

    handler = app.exception_handlers.get(RequestValidationError)
    assert handler is not None
    assert handler.__module__ == "app.main", (
        f"the registered handler is {handler.__module__}.{handler.__qualname__}, "
        "which is FastAPI's default -- ours is not installed"
    )


#: Body fields whose value must never come back in an error. Kept as a list of
#: what is worst rather than as the definition of what is covered: the handler
#: is app-wide, so this drives the sampling below and not the protection.
SECRET_BODY_FIELDS = {
    "payment_details",
    "custom_instructions",
    "password",
    "new_password",
    "current_password",
    "temp_password",
    "api_key",
    "llm_api_key",
    "secret",
    "client_secret",
    "token",
    "refresh_token",
    "totp_secret",
}


def _routes_carrying_a_secret_body():
    """Every route whose request body can hold one of those fields."""
    import inspect
    import typing

    from app.main import app
    from pydantic import BaseModel

    def walk(routes):
        found = []
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None and hasattr(inner, "routes"):
                found += walk(inner.routes)
            elif getattr(route, "path", None):
                found.append(route)
        return found

    for route in walk(app.routes):
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        # get_type_hints, not signature().parameters: every api module carries
        # `from __future__ import annotations`, so the raw annotation is the
        # *string* "ConfigUpdateRequest" and an issubclass check against it
        # silently matches nothing. That is what the vacuity guard caught.
        try:
            hints = typing.get_type_hints(endpoint)
        except Exception:  # noqa: BLE001 - an unresolvable hint is not a finding
            continue
        for name, model in hints.items():
            if name == "return":
                continue
            if not (inspect.isclass(model) and issubclass(model, BaseModel)):
                continue
            if set(model.model_fields) & SECRET_BODY_FIELDS:
                yield route, model
                break


def test_the_routes_that_can_receive_a_secret_are_still_found():
    """The walk itself, so the sampling test below cannot go quiet."""
    checked = list(_routes_carrying_a_secret_body())
    assert len(checked) >= 5, f"only found {len(checked)} such routes; the walk is wrong"
    paths = {route.path for route, _ in checked}
    # The one that was actually leaking a stored secret, named individually.
    assert "/api/admin/tenants/{tenant_id}/config" in paths, paths


def test_no_422_anywhere_echoes_what_it_rejected():
    """Asked by making real requests, against every shape of route.

    The point of going app-wide is that this needs no list to stay true, so
    the test deliberately includes a route nobody would have curated: the
    inbox reply, where the echoed value is the message a business is sending a
    customer. That is the one that was found by tripping over it.
    """
    from app.main import app
    from fastapi.testclient import TestClient

    secret = "Meezan-0123456789-PK36MEZN0001234567890123"
    client = TestClient(app, raise_server_exceptions=False)

    # No auth: an unauthenticated 401 tells us nothing, so these are the routes
    # that validate before they authenticate, plus deliberately malformed
    # bodies that fail on a *different* field so `input` carries the whole body.
    probes = [
        ("/api/auth/signup", {"password": secret}),
        ("/api/auth/login", {"password": secret}),
        ("/api/auth/reset-password", {"token": secret}),
        ("/api/team/invitations/accept", {"token": secret, "name": 1}),
        ("/api/conversations/00000000-0000-0000-0000-000000000000/reply", {"body": secret}),
        ("/api/config", {"payment_details": secret, "voice_reply_mode": 7}),
    ]
    leaked = []
    for path, body in probes:
        for method in ("post", "put"):
            response = getattr(client, method)(path, json=body)
            if response.status_code == 422 and secret in response.text:
                leaked.append(f"{method.upper()} {path}")
    assert not leaked, f"these echoed the rejected value in a 422: {sorted(set(leaked))}"


def test_the_probes_actually_reach_validation():
    """Guard against the test above passing because every probe 401'd or 404'd
    before pydantic ever ran, which would make it prove nothing."""
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)
    got_422 = [
        path
        for path, body in [
            ("/api/auth/signup", {"password": "x" * 20}),
            ("/api/auth/login", {"password": "x" * 20}),
            ("/api/auth/reset-password", {"token": "x" * 20}),
        ]
        if client.post(path, json=body).status_code == 422
    ]
    assert len(got_422) == 3, f"only {got_422} reached validation"
