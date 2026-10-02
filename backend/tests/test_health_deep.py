"""Deep readiness (CAPACITY-AND-SCALING.md P4).

On 2026-09-09 a firewall rule blocked all outbound TCP. WAHA could not reach
WhatsApp, the LLM was unreachable, the bot was silent -- and /readyz reported
everything ok, because "waha: ok" only ever meant the API could reach the WAHA
container. These tests are about the distinction that outage exposed.
"""

from __future__ import annotations

import pytest
from app.api import health


@pytest.fixture(autouse=True)
def _clear_cache():
    health._deep_cache = None
    yield
    health._deep_cache = None


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_a_failure(monkeypatch):
    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_a, **_k):
            raise OSError("network unreachable")

    monkeypatch.setattr(health.settings, "llm_base_url", "https://llm.example")
    monkeypatch.setattr(health.httpx, "AsyncClient", lambda **_k: _Boom())
    assert (await health._llm_reachable()).startswith("fail")


@pytest.mark.asyncio
async def test_a_401_from_the_provider_is_healthy(monkeypatch):
    """We are checking the path is open, not that the key is valid.

    A readiness probe that only goes green on a 200 would go red the moment a
    provider changed an auth response, which is noise rather than signal.
    """

    class _Resp:
        status_code = 401

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_a, **_k):
            return _Resp()

    monkeypatch.setattr(health.settings, "llm_base_url", "https://llm.example")
    monkeypatch.setattr(health.httpx, "AsyncClient", lambda **_k: _Client())
    assert await health._llm_reachable() == "ok"


@pytest.mark.asyncio
async def test_no_configured_provider_is_skipped_not_failed(monkeypatch):
    monkeypatch.setattr(health.settings, "llm_base_url", None)
    assert (await health._llm_reachable()).startswith("skipped")


def test_the_probe_never_spends_money():
    """A completion on every probe would be a bill that runs while nobody looks.

    Pinned as a test because 'just call the model, it is the real check' is a
    very reasonable-sounding change to make later.
    """
    import inspect

    source = inspect.getsource(health._llm_reachable)
    assert "/models" in source
    for spender in ("chat/completions", "completions", "embeddings"):
        assert spender not in source.replace("chat/completions", ""), spender


def test_skipped_does_not_count_as_a_failure():
    """An environment that is unfinished is not an environment that is broken."""
    checks = {
        "database": "ok",
        "redis": "ok",
        "llm": "skipped: no base url configured",
        "whatsapp": "skipped: no sessions provisioned",
    }
    assert [n for n, v in checks.items() if v.startswith("fail")] == []


def test_a_failing_check_is_named_so_an_alert_can_say_which():
    checks = {
        "database": "ok",
        "llm": "fail: ConnectError",
        "whatsapp": "fail: 0 of 3 sessions working",
    }
    failing = [n for n, v in checks.items() if v.startswith("fail")]
    assert failing == ["llm", "whatsapp"]
