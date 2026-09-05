"""NOWEB store configuration at session-create time (DESIGN.md §5.1).

The store must stay enabled — sends and chat resolution 400 without it — but
``fullSync`` is what makes WAHA pull the linked number's entire WhatsApp history
into its own store. Measured live: one test number cached 19,471 messages (27 MB
of sqlite, plus 6,646 lid-mapping files) to serve a product that had used 41 of
them. At ~1.3 KB per historical message and ~4 KB per contact ever seen, a busy
five-year-old business number costs the better part of a gigabyte, which
``backup.sh`` then tars nightly and keeps for 14 days.

Nothing reads that history: conversation context comes from Postgres, and the
client exposes no chat/contact listing endpoints. So it is pure cost.
"""

from __future__ import annotations

import pytest
from app.waha import client as client_module
from app.waha.client import WahaClient


class _FakeRequest:
    def __init__(self) -> None:
        self.payload: dict = {}

    async def __call__(self, _method: str, _path: str, **kwargs):
        self.payload = kwargs.get("json") or {}
        return {"ok": True}


def _client(fake: _FakeRequest) -> WahaClient:
    waha = WahaClient(base_url="http://waha", api_key="k")
    waha._request = fake  # type: ignore[method-assign]
    return waha


@pytest.mark.asyncio
async def test_noweb_store_enabled_but_not_full_sync_by_default():
    """The store is required; the history backfill is not."""
    fake = _FakeRequest()
    await _client(fake).create_session("s1", engine="NOWEB")

    store = fake.payload["config"]["noweb"]["store"]
    assert store["enabled"] is True
    assert store["fullSync"] is False


@pytest.mark.asyncio
async def test_full_sync_can_be_turned_back_on(monkeypatch):
    """An operator can opt a deployment back into history backfill."""
    monkeypatch.setattr(client_module.settings, "waha_full_sync", True)
    fake = _FakeRequest()
    await _client(fake).create_session("s1", engine="NOWEB")

    assert fake.payload["config"]["noweb"]["store"]["fullSync"] is True


@pytest.mark.asyncio
async def test_non_noweb_engine_gets_no_store_config():
    """Only NOWEB needs the store block; WEBJS must not be sent one."""
    fake = _FakeRequest()
    await _client(fake).create_session("s1", engine="WEBJS")

    assert "noweb" not in fake.payload.get("config", {})
