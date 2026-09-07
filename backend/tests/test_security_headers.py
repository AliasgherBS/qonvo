"""Response security headers on the API (and the dashboard's, checked by proxy).

Both hosts were serving none of these. That is not a subtle gap: a JSON
endpoint with no `nosniff` can be coerced into executing, one with no
`Referrer-Policy` leaks its own URL onward, and a dashboard with no
`frame-ancestors` can be framed by anyone.

Asserted here rather than trusted to a proxy on purpose. This API is reached
through a Cloudflare Tunnel today and will sit behind Caddy on a VPS later; a
header configured in the proxy silently disappears when the proxy changes.
"""

from __future__ import annotations

import pytest
from app.main import _SECURITY_HEADERS
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


REQUIRED = [
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "X-Frame-Options",
    "Content-Security-Policy",
]


@pytest.mark.parametrize("header", REQUIRED)
def test_a_successful_response_carries_it(client, header):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert header in response.headers, header


@pytest.mark.parametrize("header", REQUIRED)
def test_an_error_response_carries_it_too(client, header):
    """Error paths are the ones that get forgotten, and a 404 body is still a
    body a browser will sniff."""
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
    assert header in response.headers, header


@pytest.mark.parametrize("header", REQUIRED)
def test_an_unauthorised_response_carries_it(client, header):
    """The response an attacker sees most often."""
    response = client.get("/api/config")

    assert response.status_code in (401, 403)
    assert header in response.headers, header


def test_nosniff_is_exact():
    """The only valid value. A typo here is a header that does nothing while
    looking present."""
    assert _SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"


def test_hsts_is_long_enough_to_matter():
    """A short max-age means the protection expires between visits."""
    value = _SECURITY_HEADERS["Strict-Transport-Security"]
    max_age = int(value.split("max-age=")[1].split(";")[0])

    assert max_age >= 15_552_000  # six months, the usual floor
    assert "includeSubDomains" in value


def test_the_api_csp_allows_nothing():
    """This host serves JSON. Any resource loading at all would be a surprise,
    so the policy is default-src 'none' rather than a curated allowlist."""
    csp = _SECURITY_HEADERS["Content-Security-Policy"]

    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_referrer_policy_does_not_leak_the_path_cross_origin():
    """The reason this pass happened: a provider appended a session token to a
    URL, and a permissive policy sends the whole thing onward as Referer."""
    policy = _SECURITY_HEADERS["Referrer-Policy"]

    assert policy in ("strict-origin-when-cross-origin", "no-referrer", "same-origin")


def test_a_route_may_override_a_default(client):
    """setdefault, not assignment. The docs UI needs a looser CSP than
    default-src 'none', and a hard assignment here would break it while looking
    like a security improvement."""
    import inspect

    from app import main

    source = inspect.getsource(main._security_headers)
    assert "setdefault" in source
