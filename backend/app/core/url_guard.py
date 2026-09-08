"""Refuse to fetch a URL that points inside our own network (teardown X3).

``fetch_url_text`` took the URL straight from the request, followed redirects,
and had no scheme allowlist, no host validation and no private-range check.
Nothing in the backend imported ``ipaddress``.

The fetch runs in the worker, on the Docker network, where ``postgres``,
``redis``, ``waha``, ``minio`` and ``api`` all resolve by name, and whatever
comes back is chunked, embedded and made readable in the tenant's own
dashboard. So this was not a blind request forgery: it was a read primitive
with the response delivered to the attacker's own screen. Adding a website
source pointing at ``http://api:8000/metrics`` was enough. On a VPS the same
path reaches the cloud metadata endpoint on ``169.254.169.254``, which is how
this class of bug usually ends with somebody else holding the instance role.

**Validated per hop, not once.** A host that is public when checked can
redirect to a private one, so checking the URL and then handing it to a client
with ``follow_redirects=True`` checks the one address that was never the
problem. The fetch below drives the redirect chain itself and validates every
hop.

**What is left.** Between resolving a name and connecting to it, the answer can
change: the classic DNS rebinding window. Closing that means connecting to the
validated address and carrying the original name in the ``Host`` header, which
breaks TLS certificate validation for https and is a larger change than this.
It is a narrow window needing an attacker-controlled authoritative server, and
it is not what made this reachable, which was that ``api`` resolved and nobody
looked. Recorded rather than quietly left out.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import logger

__all__ = [
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "UnsafeUrlError",
    "fetch_public_url",
    "validate_public_url",
]

ALLOWED_SCHEMES = ("http", "https")

#: A knowledge page is prose. Anything past this is a download rather than a
#: page, and the previous code would happily have read all of it into memory in
#: the worker before anybody looked at the size.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

#: Enough for the usual `example.com` -> `www.example.com` -> https chain, not
#: enough to be walked around a validator or to loop.
MAX_REDIRECTS = 5


class UnsafeUrlError(ValueError):
    """The URL is not something we are willing to fetch.

    A ``ValueError`` because that is what the ingestion path already treats as
    "this source is bad, tell the owner" rather than "the worker broke".
    """


def _address_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether this address is out on the internet rather than next to us.

    ``is_global`` alone is not enough on its own account: it is False for
    exactly the ranges we care about, but an IPv4-mapped IPv6 address
    (``::ffff:127.0.0.1``) reports as not-global for the wrapper rather than
    for the address inside it in some versions, so the mapping is unwrapped
    first and judged on its own terms.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # includes 169.254.169.254, the metadata endpoint
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve {host!r}") from exc
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def validate_public_url(url: str) -> str:
    """Return the URL if it is safe to fetch, else raise :class:`UnsafeUrlError`.

    Every address the hostname resolves to has to be public, not merely the
    first one. A name answering with one public and one loopback address would
    otherwise pass here and connect to whichever the OS preferred.
    """
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        # file://, gopher://, and the rest. The scheme is the cheapest and
        # widest hole: `file:///etc/passwd` needs no network at all.
        raise UnsafeUrlError("only http and https addresses can be added as a website")

    if parsed.username or parsed.password:
        # Credentials in the URL would be logged by us and sent to the host.
        raise UnsafeUrlError("remove the username and password from the address")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("that address has no hostname")

    # A literal address skips resolution: `http://127.0.0.1` has nothing to
    # look up, and getaddrinfo would happily hand it straight back.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = _resolve(host)
    else:
        addresses = [literal]

    if not addresses:
        raise UnsafeUrlError(f"could not resolve {host!r}")

    if settings.knowledge_allow_private_urls:
        # Development only, and off by default. Our own stack lives on
        # 127.0.0.1 here, so without this a local test page cannot be ingested
        # on this machine at all.
        logger.warning(f"private URL allowed by configuration: {host}")
        return url.strip()

    for ip in addresses:
        if not _address_is_public(ip):
            # Deliberately vague about which address. Reporting "resolved to
            # 172.19.0.4" back to the tenant turns a refusal into a network
            # map, which is a smaller version of the thing being fixed.
            raise UnsafeUrlError(
                "that address points inside a private network, so it cannot be reached"
            )

    return url.strip()


async def fetch_public_url(
    url: str, *, request_timeout: float = 20.0, user_agent: str
) -> httpx.Response:
    """GET a public URL, validating every hop and capping the response.

    Drives the redirect chain by hand because that is the only way to check
    each hop: ``follow_redirects=True`` validates the one URL that was never
    the danger and then follows wherever it is sent.
    """
    current = validate_public_url(url)

    async with httpx.AsyncClient(
        timeout=request_timeout,
        follow_redirects=False,
        headers={"User-Agent": user_agent},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise UnsafeUrlError("that address redirected to nowhere")
                    # Relative redirects are normal, so resolve against the
                    # current URL before validating.
                    current = validate_public_url(str(httpx.URL(current).join(location)))
                    continue

                resp.raise_for_status()

                # Read with a cap rather than `await resp.aread()`. A
                # Content-Length can be absent or a lie, so the limit has to be
                # enforced on what actually arrives.
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise UnsafeUrlError(
                            "that page is too large to read as knowledge "
                            f"(limit {MAX_RESPONSE_BYTES // (1024 * 1024)} MB)"
                        )
                # Hand back a response the caller can read `.text` from, with
                # the encoding httpx worked out from the headers preserved.
                return httpx.Response(
                    status_code=resp.status_code,
                    headers=resp.headers,
                    content=bytes(body),
                    request=resp.request,
                )

    raise UnsafeUrlError("that address redirected too many times")
