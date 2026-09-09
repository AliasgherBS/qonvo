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


def test_the_router_installs_the_quiet_route_class():
    """The strip happens in a route class rather than an app-wide handler, so
    it stays a property of the endpoints that carry secrets. If the router is
    ever rebuilt without it, every 422 here starts echoing again."""
    from app.api.config import QuietValidationRoute, router

    assert router.route_class is QuietValidationRoute


#: Body fields whose value must never come back in an error. ``payment_details``
#: is the receiving account the rep reads out; ``custom_instructions`` is up to
#: 2,000 characters of the owner's own business writing; the rest are
#: credentials by name.
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
    """Every route whose request body can hold one of those fields.

    Asserting on one named router is what let this regress: the test above
    passed for the whole time ``PUT /api/admin/tenants/{id}/config`` was
    echoing, because that route accepts ``ConfigUpdateRequest`` from a
    *different* router. The property is "no route that can receive a secret
    echoes it", so it is asked of the route table.
    """
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
        # silently matches nothing. That is what the vacuity guard below caught.
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


def test_every_route_that_can_receive_a_secret_has_the_quiet_422():
    from app.api.config import QuietValidationRoute

    checked = list(_routes_carrying_a_secret_body())
    # If this finds nothing the test is vacuous, which is how the version of
    # this file that only knew about one router reported success.
    assert len(checked) >= 2, f"only found {len(checked)} such routes; the walk is wrong"

    offenders = [
        f"{sorted(route.methods)[0]} {route.path} (body {model.__name__}, "
        f"{type(route).__name__})"
        for route, model in checked
        if not isinstance(route, QuietValidationRoute)
    ]
    assert not offenders, (
        "these accept a secret-bearing body and would echo it in a 422. Build "
        "their router with route_class=QuietValidationRoute: " + ", ".join(sorted(offenders))
    )


def test_the_admin_config_route_is_one_of_them():
    """Named individually, because this is the route that was actually leaking
    and a count regressing by one is easy to miss."""
    found = {
        (route.path, model.__name__) for route, model in _routes_carrying_a_secret_body()
    }
    assert ("/api/admin/tenants/{tenant_id}/config", "ConfigUpdateRequest") in found, found
