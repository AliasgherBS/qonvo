"""Typed async WAHA REST client (DESIGN.md §1 send/session API).

All calls are authed with ``X-Api-Key``. This is the *raw* transport — outbound
message sends must go through :mod:`app.waha.send_gateway`, never this client
directly (DESIGN.md §5.6).
"""

from __future__ import annotations

import contextlib
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings


class WahaError(Exception):
    """Non-2xx response from WAHA."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"WAHA request failed ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class WahaClient:
    """Thin typed wrapper over the WAHA REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = (base_url or settings.waha_base_url).rstrip("/")
        self._api_key = api_key or settings.waha_api_key
        self._timeout = timeout
        self._external_client = client
        self._client = client

    async def __aenter__(self) -> WahaClient:
        self._ensure_client()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"X-Api-Key": self._api_key},
                timeout=self._timeout,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = self._ensure_client()
        resp = await client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise WahaError(resp.status_code, resp.text)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.content

    # --- Messaging ------------------------------------------------------- #
    async def send_text(
        self,
        session: str,
        chat_id: str,
        text: str,
        *,
        reply_to: str | None = None,
        link_preview: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session": session,
            "chatId": chat_id,
            "text": text,
            "linkPreview": link_preview,
        }
        if reply_to:
            payload["reply_to"] = reply_to
        return await self._request("POST", "/api/sendText", json=payload)

    async def send_voice(
        self,
        session: str,
        chat_id: str,
        *,
        url: str | None = None,
        data: str | None = None,
        convert: bool = True,
    ) -> dict[str, Any]:
        """Send a voice note. WAHA requires OPUS-in-OGG; ``convert=True`` lets
        WAHA transcode other inputs (DESIGN.md §1)."""
        file_obj: dict[str, Any] = {"mimetype": "audio/ogg; codecs=opus"}
        if url:
            file_obj["url"] = url
        if data:
            file_obj["data"] = data
        payload = {
            "session": session,
            "chatId": chat_id,
            "file": file_obj,
            "convert": convert,
        }
        return await self._request("POST", "/api/sendVoice", json=payload)

    async def send_image(
        self,
        session: str,
        chat_id: str,
        *,
        url: str | None = None,
        data: str | None = None,
        mimetype: str = "image/jpeg",
        filename: str | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/sendImage",
            json=self._media_payload(
                session, chat_id, url, data, mimetype, filename, caption
            ),
        )

    async def send_file(
        self,
        session: str,
        chat_id: str,
        *,
        url: str | None = None,
        data: str | None = None,
        mimetype: str = "application/octet-stream",
        filename: str | None = None,
        caption: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/sendFile",
            json=self._media_payload(
                session, chat_id, url, data, mimetype, filename, caption
            ),
        )

    @staticmethod
    def _media_payload(
        session: str,
        chat_id: str,
        url: str | None,
        data: str | None,
        mimetype: str,
        filename: str | None,
        caption: str | None,
    ) -> dict[str, Any]:
        file_obj: dict[str, Any] = {"mimetype": mimetype}
        if url:
            file_obj["url"] = url
        if data:
            file_obj["data"] = data
        if filename:
            file_obj["filename"] = filename
        payload: dict[str, Any] = {"session": session, "chatId": chat_id, "file": file_obj}
        if caption:
            payload["caption"] = caption
        return payload

    async def send_seen(self, session: str, chat_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/sendSeen", json={"session": session, "chatId": chat_id}
        )

    async def start_typing(self, session: str, chat_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/startTyping", json={"session": session, "chatId": chat_id}
        )

    async def stop_typing(self, session: str, chat_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/api/stopTyping", json={"session": session, "chatId": chat_id}
        )

    # --- Sessions -------------------------------------------------------- #
    async def create_session(
        self,
        name: str,
        *,
        webhooks: list[dict[str, Any]] | None = None,
        engine: str | None = None,
        start: bool = True,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {}
        if webhooks:
            config["webhooks"] = webhooks
        if engine:
            config["metadata"] = {"engine": engine}
        # The NOWEB engine needs its store enabled at create time, otherwise
        # sends (and chat/contact resolution) 400 with "Enable NOWEB store".
        # fullSync pulls history so the store is populated for a fresh number.
        if engine and engine.upper() == "NOWEB":
            config["noweb"] = {"store": {"enabled": True, "fullSync": True}}
        payload: dict[str, Any] = {"name": name, "start": start}
        if config:
            payload["config"] = config
        return await self._request("POST", "/api/sessions", json=payload)

    async def get_session(self, name: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/sessions/{name}")

    async def start_session(self, name: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/sessions/{name}/start")

    async def stop_session(self, name: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/sessions/{name}/stop")

    async def restart_session(self, name: str) -> dict[str, Any]:
        """Stop then start.

        A bare ``start`` on a FAILED session is a no-op: WAHA still considers
        it running and answers ``Session is already running``, which is why
        clicking Start in the Fleet console never revived a dead session. The
        stop is best-effort because a session WAHA has already torn down
        returns an error that must not block the start.
        """
        with contextlib.suppress(WahaError):
            await self.stop_session(name)
        return await self.start_session(name)

    async def logout_session(self, name: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/sessions/{name}/logout")

    async def delete_session(self, name: str) -> dict[str, Any]:
        """Fully remove a WAHA session (used when offboarding a tenant)."""
        return await self._request("DELETE", f"/api/sessions/{name}")

    async def get_qr(self, name: str) -> bytes:
        """Fetch the current QR image (expires ~20s — poll & re-render, §10)."""
        return await self._request("GET", f"/api/{name}/auth/qr")

    # --- Media ----------------------------------------------------------- #
    async def download_media(self, url: str) -> bytes:
        """Download media immediately on receipt (WAHA URLs are not durable, §12.3).

        WAHA advertises media URLs using its *own* configured host (e.g.
        ``http://localhost:3000/api/files/...``), which isn't reachable from
        inside our network — so keep only the path/query and fetch it through the
        client's WAHA base URL (``http://waha:3000``).
        """
        parts = urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        client = self._ensure_client()
        resp = await client.get(path or url)
        if resp.status_code >= 400:
            raise WahaError(resp.status_code, resp.text)
        return resp.content
