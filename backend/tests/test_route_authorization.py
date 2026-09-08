"""Which routes a staff seat may reach (teardown X1).

``require_owner`` existed and was correct, and was used in two modules out of
twenty-one. Everything else was gated by ``require_tenant``, which any member of
the tenant satisfies. So a receptionist with a staff login could cancel the
subscription, change the plan, turn the whole rep off, and fetch a pairing QR.

The worst of them was ``PUT /api/config``, which accepts ``payment_details`` --
the free text the ``share_payment_details`` skill reads out verbatim when a
customer asks how to pay. A staff seat could substitute their own account
number, and the business's own WhatsApp number would tell its customers to pay
it, with nothing on any screen showing it happened. Verified live before the
fix: HTTP 200.

These tests are written against the route table rather than by making requests,
because the property is "no state-changing route is reachable by staff", and a
test per route would pass while the next route added quietly did not have one.
"""

from __future__ import annotations

import inspect

import pytest
from app.api.deps import require_owner, require_tenant, require_verified_owner
from app.main import app


def _all_routes():
    """Every real route, flattened.

    This FastAPI version keeps each `include_router` as an `_IncludedRouter`
    wrapper rather than splicing its routes into `app.routes`, so iterating the
    app directly yields four routes and twelve wrappers. A test that missed
    that would pass while checking nothing, which is how the first version of
    this file "passed".
    """

    def walk(routes):
        found = []
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None and hasattr(inner, "routes"):
                found += walk(inner.routes)
            elif getattr(route, "path", None):
                found.append(route)
        return found

    return walk(app.routes)


def _by_endpoint() -> dict[tuple[str, str], object]:
    """``(path, method)`` -> route, so a lookup is not a walk of the whole app."""
    table: dict[tuple[str, str], object] = {}
    for route in _all_routes():
        for method in getattr(route, "methods", set()) or set():
            table[(getattr(route, "path", ""), method)] = route
    return table


def _gate(route) -> str:
    """Which dependency guards this route: ``owner``, ``tenant`` or ``none``."""
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return "none"
    try:
        params = inspect.signature(endpoint).parameters
    except (TypeError, ValueError):
        return "none"
    found = set()
    for param in params.values():
        default = param.default
        dependency = getattr(default, "dependency", None)
        # require_verified_owner is require_owner plus a confirmed address, so
        # it counts as owner here. Treating it as ungated would make the two
        # routes it guards look like regressions for being *more* strictly
        # gated, which is how a test starts arguing against its own purpose.
        if dependency in (require_owner, require_verified_owner):
            found.add("owner")
        elif dependency is require_tenant:
            found.add("tenant")
    if "owner" in found:
        return "owner"
    if "tenant" in found:
        return "tenant"
    return "none"


def _tenant_routes():
    """Owner-facing routes, excluding admin, webhooks and public endpoints."""
    for route in _all_routes():
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/api/") or path.startswith("/api/admin"):
            continue
        # /api/auth is how somebody becomes authenticated, so it has no gate by
        # definition. The oauth callback authenticates by its own single-use
        # state token.
        if path.startswith("/api/auth") or path.endswith("/oauth/callback"):
            continue
        # Accepting an invitation is how an invited person becomes
        # authenticated, so it cannot require an existing session. It
        # authenticates by the token emailed to the invitee, which is
        # single-use: _resolve_invite only accepts status "pending" and accept
        # sets "accepted". Verified by
        # test_accepting_an_invitation_is_authenticated_by_its_own_token.
        if path == "/api/team/invitations/accept":
            continue
        yield path, methods


#: Routes a staff seat is meant to reach. Everything else that changes state
#: must be owner-only, and a new route is owner-only until it appears here.
#:
#: The set is the one the product already promised: read the inbox, reply, take
#: over, add knowledge, see what the plan allows. The Team page says "Owners
#: manage the team and billing", and now that is true.
STAFF_ALLOWED: set[tuple[str, str]] = {
    ("/api/conversations", "GET"),
    ("/api/conversations/{conversation_id}/messages", "GET"),
    ("/api/conversations/{conversation_id}/takeover", "POST"),
    ("/api/conversations/{conversation_id}/release", "POST"),
    ("/api/conversations/{conversation_id}/reply", "POST"),
    ("/api/knowledge/sources", "GET"),
    ("/api/knowledge/sources", "POST"),
    ("/api/knowledge/sources/{source_id}", "GET"),
    ("/api/knowledge/sources/{source_id}", "PUT"),
    ("/api/knowledge/sources/{source_id}/upload", "POST"),
    ("/api/knowledge/usage", "GET"),
    ("/api/knowledge/gaps", "GET"),
    ("/api/notifications", "GET"),
    ("/api/notifications/{notification_id}/read", "POST"),
    ("/api/config", "GET"),
    ("/api/activation", "GET"),
    ("/api/billing", "GET"),
    ("/api/billing/plans", "GET"),
    ("/api/billing/usage", "GET"),
    ("/api/sessions", "GET"),
    ("/api/sessions/{session_name}/status", "GET"),
    ("/api/integrations", "GET"),
    ("/api/integrations/{provider}/test", "POST"),
    ("/api/integrations/google_sheets/picker-token", "GET"),
    ("/api/analytics/summary", "GET"),
    ("/api/team", "GET"),
    ("/api/account", "GET"),
    # Your own display name, which is a property of the person and not of the
    # workspace (teardown V5). Owner-gating it would leave a staff seat with
    # exactly the finding this fixes, and the payload carries no user id, so it
    # can only ever rename the subject of the caller's own token.
    ("/api/account/profile", "PATCH"),
}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def test_no_state_changing_route_is_reachable_by_staff():
    """The property, asserted once rather than per route.

    A test per endpoint would pass happily while the next endpoint somebody
    adds is quietly gated by require_tenant, which is exactly how this
    happened: require_owner was right, and nineteen modules did not use it.
    """
    routes = _by_endpoint()
    offenders = []
    for path, methods in _tenant_routes():
        for method in methods & WRITE_METHODS:
            if (path, method) in STAFF_ALLOWED:
                continue
            route = routes.get((path, method))
            if route is not None and _gate(route) != "owner":
                offenders.append(f"{method} {path} ({_gate(route)})")
    assert not offenders, (
        "these change state and are not owner-only. Either gate them with "
        "require_owner, or add them to STAFF_ALLOWED deliberately: " + ", ".join(sorted(offenders))
    )


@pytest.mark.parametrize(
    "path,method",
    [
        # The one that could cost a customer money.
        ("/api/config", "PUT"),
        ("/api/billing/cancel", "POST"),
        ("/api/billing/change-plan", "POST"),
        ("/api/billing/checkout", "POST"),
        ("/api/billing/portal", "POST"),
        ("/api/billing/payments", "GET"),
        ("/api/activation", "PUT"),
        ("/api/sessions", "POST"),
        ("/api/sessions/{session_name}/qr", "GET"),
        ("/api/integrations/{provider}", "DELETE"),
        ("/api/knowledge/sources/{source_id}", "DELETE"),
    ],
)
def test_the_named_routes_are_owner_only(path, method):
    """Each one the teardown called out, pinned individually so a regression
    names the route rather than a count."""
    route = _by_endpoint().get((path, method))
    assert route is not None, f"{method} {path} not found in the route table"
    assert _gate(route) == "owner", f"{method} {path} is {_gate(route)}"


def test_reads_a_staff_seat_needs_are_still_open():
    """Over-correcting is its own failure. Somebody working the inbox has to be
    able to see the plan's limits and what the rep is configured to do."""
    routes = _by_endpoint()
    for path, method in (
        ("/api/config", "GET"),
        ("/api/billing/usage", "GET"),
        ("/api/conversations", "GET"),
        ("/api/knowledge/sources", "GET"),
    ):
        route = routes.get((path, method))
        assert route is not None, f"{method} {path} not found in the route table"
        assert _gate(route) == "tenant", f"{method} {path} became owner-only"


def test_require_owner_is_now_used_widely():
    """The count is the finding. It was two modules out of twenty-one."""
    from pathlib import Path

    api = Path(__file__).resolve().parents[1] / "app" / "api"
    users = [p.name for p in api.glob("*.py") if "require_owner" in p.read_text()]

    assert len(users) >= 8, f"only {len(users)} modules use require_owner: {users}"


def test_accepting_an_invitation_is_authenticated_by_its_own_token():
    """The one state-changing route with no session gate, so its own
    authentication is pinned here rather than assumed.

    It is exempted in _tenant_routes because an invitee has no session yet. That
    exemption is only safe while the token is single-use and time-limited, and
    it is the kind of property a later refactor could drop without any test
    noticing.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "api" / "team.py").read_text()
    tree = ast.parse(source)
    functions = {
        node.name: ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    resolve = functions["_resolve_invite"]
    assert "status != 'pending'" in resolve, "an already-used invite must not resolve"
    assert "expires_at" in resolve, "an invite must expire"

    accept = functions["accept_invitation"]
    assert "invite.status = 'accepted'" in accept, "accepting must consume the invite"
