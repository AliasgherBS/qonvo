"""WahaClient.restart_session and the reachability gate (DESIGN.md §12.1)."""

from __future__ import annotations

import pytest
from app.waha.client import WahaClient, WahaError
from app.waha.session_health import whatsapp_reachable


class _FakeClient:
    """Records calls and optionally raises for chosen paths."""

    def __init__(self, fail_paths: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_paths = fail_paths or set()

    async def request(self, method: str, path: str, **_kwargs):
        self.calls.append((method, path))
        if path in self._fail_paths:
            raise WahaError(422, "boom")
        return {"ok": True}


def _client(fake: _FakeClient) -> WahaClient:
    waha = WahaClient(base_url="http://waha", api_key="k")
    waha._request = fake.request  # type: ignore[method-assign]
    return waha


@pytest.mark.asyncio
async def test_restart_stops_then_starts():
    """A bare start is a no-op on a FAILED session: WAHA still thinks it is
    running and answers 'Session is already running'. The stop is what makes
    the start take effect."""
    fake = _FakeClient()
    await _client(fake).restart_session("s1")
    assert fake.calls == [
        ("POST", "/api/sessions/s1/stop"),
        ("POST", "/api/sessions/s1/start"),
    ]


@pytest.mark.asyncio
async def test_start_still_runs_when_stop_fails():
    """WAHA errors when stopping a session it has already torn down. That must
    not prevent the start, or a fully dead session can never be revived."""
    fake = _FakeClient(fail_paths={"/api/sessions/s1/stop"})
    await _client(fake).restart_session("s1")
    assert ("POST", "/api/sessions/s1/start") in fake.calls


@pytest.mark.asyncio
async def test_start_failure_propagates():
    """A failing start is a real failure and the caller counts the attempt."""
    fake = _FakeClient(fail_paths={"/api/sessions/s1/start"})
    with pytest.raises(WahaError):
        await _client(fake).restart_session("s1")


@pytest.mark.asyncio
async def test_reachability_false_for_unroutable_host():
    """The gate must report False rather than raise, or one DNS failure takes
    down the whole health poll."""
    assert await whatsapp_reachable("invalid.invalid.invalid", 443) is False
