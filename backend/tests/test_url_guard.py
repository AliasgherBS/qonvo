"""Refusing to fetch our own network (teardown X3).

``fetch_url_text`` took the URL from the request, followed redirects, and had
no scheme allowlist, no host validation and no private-range check. The fetch
runs in the worker, on the Docker network, where ``postgres``, ``redis``,
``waha``, ``minio`` and ``api`` all resolve by name, and the response is
chunked, embedded and shown in the tenant's own dashboard. A website source of
``http://api:8000/metrics`` was the whole exploit.

The two tests that matter most are the redirect one and the mixed-resolution
one, because both are ways a validator that looks correct still lets the
request through: checking the URL and then following redirects checks the one
address that was never the danger, and taking the first resolved address
ignores the rest.
"""

from __future__ import annotations

import ipaddress
import socket

import httpx
import pytest
from app.core import url_guard
from app.core.url_guard import UnsafeUrlError, fetch_public_url, validate_public_url

UA = "test-agent"


@pytest.fixture
def resolves(monkeypatch):
    """Point DNS at chosen addresses, so these tests need no network."""

    def install(mapping: dict[str, list[str]]):
        def fake_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            if host not in mapping:
                raise socket.gaierror(f"no fixture for {host}")
            return [
                (
                    socket.AF_INET6 if ":" in addr else socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (addr, 0),
                )
                for addr in mapping[host]
            ]

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)

    return install


@pytest.fixture
def responds(monkeypatch):
    """Serve canned responses, so fetch_public_url can be driven end to end."""

    def install(handler):
        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient

        def client(**kwargs):
            return real(**kwargs, transport=transport)

        monkeypatch.setattr(url_guard.httpx, "AsyncClient", client)

    return install


# --- the scheme is the widest hole ------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",  # no network needed at all
        "gopher://example.com/",  # the classic protocol-smuggling scheme
        "ftp://example.com/",
        "data:text/html,hello",
        "//example.com/",  # scheme-relative, so no scheme at all
    ],
)
def test_only_http_and_https_are_fetchable(url):
    with pytest.raises(UnsafeUrlError, match="http and https"):
        validate_public_url(url)


# --- literal addresses skip DNS entirely ------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.1/",  # the short form is still loopback
        "http://10.0.0.5/",
        "http://172.19.0.4:5432/",  # a Docker bridge address
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",  # loopback wearing an IPv6 coat
    ],
)
def test_private_and_reserved_addresses_are_refused(url):
    with pytest.raises(UnsafeUrlError, match="private network"):
        validate_public_url(url)


def test_a_public_literal_is_allowed():
    assert validate_public_url("https://93.184.216.34/") == "https://93.184.216.34/"


# --- names ------------------------------------------------------------------------- #
def test_a_service_name_on_our_own_network_is_refused(resolves):
    """The exploit as reported: `api` resolves inside the worker's network."""
    resolves({"api": ["172.19.0.6"]})

    with pytest.raises(UnsafeUrlError, match="private network"):
        validate_public_url("http://api:8000/metrics")


def test_a_public_name_is_allowed(resolves):
    resolves({"example.com": ["93.184.216.34"]})

    assert validate_public_url("https://example.com/pricing")


def test_every_resolved_address_must_be_public_not_just_the_first(resolves):
    """A name answering with one public and one loopback address would pass a
    check that stopped at the first, and then connect to whichever the OS
    preferred. This is a real DNS trick, not a hypothetical one."""
    resolves({"sneaky.example": ["93.184.216.34", "127.0.0.1"]})

    with pytest.raises(UnsafeUrlError, match="private network"):
        validate_public_url("http://sneaky.example/")


def test_a_name_that_does_not_resolve_is_refused(resolves):
    resolves({})

    with pytest.raises(UnsafeUrlError, match="could not resolve"):
        validate_public_url("http://nowhere.invalid/")


def test_credentials_in_the_url_are_refused():
    with pytest.raises(UnsafeUrlError, match="username and password"):
        validate_public_url("http://user:secret@example.com/")


def test_a_url_with_no_hostname_is_refused():
    with pytest.raises(UnsafeUrlError, match="no hostname"):
        validate_public_url("http:///just-a-path")


# --- the error message must not become a network map ------------------------------- #
def test_the_refusal_does_not_report_the_resolved_address(resolves):
    """Telling the tenant "resolved to 172.19.0.6" answers the question they
    were asking. The refusal is deliberately vague."""
    resolves({"api": ["172.19.0.6"]})

    with pytest.raises(UnsafeUrlError) as caught:
        validate_public_url("http://api:8000/metrics")

    assert "172.19" not in str(caught.value)


# --- redirects, which is where a one-shot check fails ------------------------------ #
async def test_a_redirect_to_a_private_address_is_refused(resolves, responds):
    """The reason the fetch drives the chain itself. `follow_redirects=True`
    validates the first URL, which is the one the attacker made public on
    purpose, and then goes wherever it is told."""
    resolves({"public.example": ["93.184.216.34"]})
    responds(
        lambda request: httpx.Response(302, headers={"location": "http://169.254.169.254/"})
    )

    with pytest.raises(UnsafeUrlError, match="private network"):
        await fetch_public_url("http://public.example/", user_agent=UA)


async def test_a_relative_redirect_is_resolved_before_being_checked(resolves, responds):
    """A `location: /page` is normal, and joining it against the wrong base
    would either crash or validate a nonsense URL."""
    resolves({"public.example": ["93.184.216.34"]})
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "/moved"})
        return httpx.Response(200, text="the content")

    responds(handler)

    resp = await fetch_public_url("http://public.example/", user_agent=UA)

    assert resp.text == "the content"
    assert seen == ["http://public.example/", "http://public.example/moved"]


async def test_an_endless_redirect_chain_stops(resolves, responds):
    resolves({"public.example": ["93.184.216.34"]})
    responds(lambda request: httpx.Response(302, headers={"location": "/again"}))

    with pytest.raises(UnsafeUrlError, match="redirected too many times"):
        await fetch_public_url("http://public.example/", user_agent=UA)


async def test_a_redirect_with_no_location_is_refused(resolves, responds):
    resolves({"public.example": ["93.184.216.34"]})
    responds(lambda request: httpx.Response(302))

    with pytest.raises(UnsafeUrlError, match="redirected to nowhere"):
        await fetch_public_url("http://public.example/", user_agent=UA)


# --- size ------------------------------------------------------------------------- #
async def test_an_oversized_response_is_refused(resolves, responds):
    """Enforced on what arrives rather than on Content-Length, which can be
    absent or a lie. The old code read the whole body into the worker before
    anybody looked at its size."""
    resolves({"public.example": ["93.184.216.34"]})
    responds(
        lambda request: httpx.Response(200, content=b"x" * (url_guard.MAX_RESPONSE_BYTES + 1))
    )

    with pytest.raises(UnsafeUrlError, match="too large"):
        await fetch_public_url("http://public.example/", user_agent=UA)


async def test_a_normal_page_comes_back_intact(resolves, responds):
    resolves({"public.example": ["93.184.216.34"]})
    responds(lambda request: httpx.Response(200, text="<h1>Our prices</h1>"))

    resp = await fetch_public_url("http://public.example/", user_agent=UA)

    assert resp.status_code == 200
    assert "Our prices" in resp.text


async def test_a_bad_status_still_raises(resolves, responds):
    resolves({"public.example": ["93.184.216.34"]})
    responds(lambda request: httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_public_url("http://public.example/", user_agent=UA)


# --- the development escape hatch -------------------------------------------------- #
def test_private_addresses_are_allowed_only_when_configured(monkeypatch):
    """Off by default, which is the half that matters. On this machine the whole
    stack is on 127.0.0.1, so without an opt-in a local page cannot be ingested
    at all; in production the same permission is the bug."""
    assert url_guard.settings.knowledge_allow_private_urls is False

    monkeypatch.setattr(url_guard.settings, "knowledge_allow_private_urls", True)
    assert validate_public_url("http://127.0.0.1:8000/page") == "http://127.0.0.1:8000/page"


# --- and the sharp edges of the address check itself -------------------------------- #
@pytest.mark.parametrize(
    "addr,public",
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("::1", False),
        ("::ffff:10.0.0.1", False),
        ("169.254.169.254", False),
        ("224.0.0.1", False),  # multicast
        ("240.0.0.1", False),  # reserved
    ],
)
def test_the_address_classifier(addr, public):
    assert url_guard._address_is_public(ipaddress.ip_address(addr)) is public


# --- the owner is told while the dialog is still open ------------------------------- #
def test_the_api_refuses_a_private_url_as_a_400(resolves):
    """The worker's check is the one that matters, because it sees each redirect
    hop. This one exists so "Add website" fails in front of the person who
    typed it, rather than turning the source to "error" a few seconds later,
    which reads as the product breaking."""
    from app.api.knowledge import _checked_url
    from fastapi import HTTPException

    resolves({"api": ["172.19.0.6"]})

    with pytest.raises(HTTPException) as caught:
        _checked_url("http://api:8000/metrics")

    assert caught.value.status_code == 400
    assert "private network" in str(caught.value.detail)


def test_the_api_passes_a_public_url_through_unchanged(resolves):
    resolves({"example.com": ["93.184.216.34"]})
    from app.api.knowledge import _checked_url

    assert _checked_url("  https://example.com/pricing  ") == "https://example.com/pricing"


def test_the_api_leaves_a_missing_url_alone():
    """A text or file source has no URL, and validating None must not become a
    400 that blocks every non-website source."""
    from app.api.knowledge import _checked_url

    assert _checked_url(None) is None
