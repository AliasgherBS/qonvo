"""Google OAuth flow: authorize URL, code exchange, refresh, revoke, state, cache.

Fully hermetic — ``httpx.MockTransport`` stands in for Google and the ``fake_redis``
fixture for Redis. No network, no google client libraries, no monkeypatching of
internals.
"""

from __future__ import annotations

import base64
import json
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.core.security import decrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS, token_cache
from app.integrations import google_oauth as oauth
from app.integrations.oauth_state import consume_state, issue_state, state_key
from app.integrations.scopes import (
    CALENDAR_FREEBUSY_SCOPE,
    CALENDAR_SCOPE,
    SHEETS_SCOPE,
    missing_scopes,
    scopes_for,
)


@pytest.fixture(autouse=True)
def _oauth_configured(monkeypatch):
    monkeypatch.setattr(oauth.settings, "google_oauth_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(oauth.settings, "google_oauth_client_secret", "csecret")
    monkeypatch.setattr(oauth.settings, "google_oauth_redirect_base", "https://qonvo.test")


def _id_token(claims: dict) -> str:
    """An unsigned JWT-shaped token — enough for the email-claim reader."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- authorize URL --------------------------------------------------------------- #
def test_authorize_url_carries_offline_and_consent():
    url = oauth.authorize_url(state="st8", scopes=scopes_for(GOOGLE_CALENDAR))
    q = parse_qs(urlparse(url).query)

    assert url.startswith(oauth.AUTH_ENDPOINT)
    assert q["access_type"] == ["offline"]
    # Without prompt=consent a *re*-connect returns no refresh token at all, and
    # we'd silently keep serving the stale one until it died.
    assert q["prompt"] == ["consent"]
    assert q["response_type"] == ["code"]
    assert q["state"] == ["st8"]
    assert q["redirect_uri"] == ["https://qonvo.test/api/integrations/oauth/callback"]
    # Widening each grant to the other provider's scopes would worsen the
    # shared-grant revocation coupling for no gain.
    assert "include_granted_scopes" not in q


def test_authorize_url_scopes_are_space_joined():
    url = oauth.authorize_url(state="s", scopes=scopes_for(GOOGLE_CALENDAR))
    granted = parse_qs(urlparse(url).query)["scope"][0].split()
    assert CALENDAR_SCOPE in granted
    assert CALENDAR_FREEBUSY_SCOPE in granted


def test_authorize_url_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(oauth.settings, "google_oauth_client_id", None)
    with pytest.raises(oauth.GoogleOAuthError):
        oauth.authorize_url(state="s", scopes=[SHEETS_SCOPE])


def test_redirect_uri_strips_trailing_slash(monkeypatch):
    monkeypatch.setattr(oauth.settings, "google_oauth_redirect_base", "https://qonvo.test/")
    assert oauth.redirect_uri() == "https://qonvo.test/api/integrations/oauth/callback"


# --- code exchange --------------------------------------------------------------- #
async def test_exchange_code_parses_granted_scopes_and_email():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == oauth.TOKEN_ENDPOINT
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["abc"]
        return httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "1//rt",
                "expires_in": 3599,
                # Granted, not requested — Google allows partial consent.
                "scope": f"{CALENDAR_SCOPE} openid email",
                "id_token": _id_token({"email": "owner@example.com"}),
            },
        )

    async with _client(handler) as client:
        bundle = await oauth.exchange_code("abc", client=client)

    assert bundle.access_token == "at"
    assert bundle.refresh_token == "1//rt"
    assert bundle.expires_in == 3599
    assert CALENDAR_SCOPE in bundle.granted_scopes
    assert bundle.account_email == "owner@example.com"


async def test_exchange_code_detects_partial_consent():
    """Google granted identity but not the scope the feature needs."""

    def handler(_request):
        return httpx.Response(
            200,
            json={"access_token": "at", "refresh_token": "r", "expires_in": 60, "scope": "openid"},
        )

    async with _client(handler) as client:
        bundle = await oauth.exchange_code("abc", client=client)

    assert missing_scopes(GOOGLE_CALENDAR, bundle.granted_scopes) == {CALENDAR_SCOPE}


async def test_exchange_code_survives_missing_expiry_and_id_token():
    def handler(_request):
        return httpx.Response(200, json={"access_token": "at", "scope": SHEETS_SCOPE})

    async with _client(handler) as client:
        bundle = await oauth.exchange_code("abc", client=client)

    assert bundle.expires_in == 0
    assert bundle.account_email is None
    assert bundle.refresh_token is None


async def test_exchange_code_tolerates_unparseable_id_token():
    def handler(_request):
        return httpx.Response(
            200,
            json={"access_token": "at", "expires_in": 60, "id_token": "not-a-jwt"},
        )

    async with _client(handler) as client:
        bundle = await oauth.exchange_code("abc", client=client)

    assert bundle.account_email is None


async def test_exchange_code_raises_on_error_response():
    def handler(_request):
        return httpx.Response(
            400, json={"error": "invalid_request", "error_description": "bad code"}
        )

    async with _client(handler) as client:
        with pytest.raises(oauth.GoogleOAuthError, match="invalid_request"):
            await oauth.exchange_code("abc", client=client)


# --- refresh --------------------------------------------------------------------- #
async def test_refresh_access_token_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["1//rt"]
        return httpx.Response(
            200, json={"access_token": "fresh", "expires_in": 3600, "scope": CALENDAR_SCOPE}
        )

    async with _client(handler) as client:
        bundle = await oauth.refresh_access_token("1//rt", client=client)

    assert bundle.access_token == "fresh"
    # A refresh response never carries a refresh_token; the caller keeps its own.
    assert bundle.refresh_token is None


async def test_refresh_invalid_grant_raises_reauth_required():
    """This is what Google returns after the owner revokes access — not retryable."""

    def handler(_request):
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": "Token has been expired"},
        )

    async with _client(handler) as client:
        with pytest.raises(oauth.GoogleReauthRequired):
            await oauth.refresh_access_token("1//dead", client=client)


async def test_refresh_other_error_is_not_reauth_required():
    def handler(_request):
        return httpx.Response(500, json={"error": "backendError"})

    async with _client(handler) as client:
        with pytest.raises(oauth.GoogleOAuthError) as exc:
            await oauth.refresh_access_token("1//rt", client=client)
    assert not isinstance(exc.value, oauth.GoogleReauthRequired)


async def test_refresh_handles_non_json_error_body():
    def handler(_request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    async with _client(handler) as client:
        with pytest.raises(oauth.GoogleOAuthError):
            await oauth.refresh_access_token("1//rt", client=client)


# --- revoke ---------------------------------------------------------------------- #
async def test_revoke_returns_true_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == oauth.REVOKE_ENDPOINT
        return httpx.Response(200)

    async with _client(handler) as client:
        assert await oauth.revoke("1//rt", client=client) is True


async def test_revoke_returns_false_instead_of_raising():
    def handler(_request):
        return httpx.Response(400, json={"error": "invalid_token"})

    async with _client(handler) as client:
        assert await oauth.revoke("1//rt", client=client) is False


async def test_revoke_returns_false_on_transport_error():
    def handler(_request):
        raise httpx.ConnectError("no route to host")

    async with _client(handler) as client:
        assert await oauth.revoke("1//rt", client=client) is False


# --- CSRF state ------------------------------------------------------------------ #
async def test_state_round_trip(fake_redis):
    tenant_id = uuid.uuid4()
    token = await issue_state(
        fake_redis, tenant_id=tenant_id, provider=GOOGLE_SHEETS, return_to="/integrations"
    )
    resolved = await consume_state(fake_redis, token)

    assert resolved is not None
    assert resolved.tenant_id == tenant_id
    assert resolved.provider == GOOGLE_SHEETS
    assert resolved.return_to == "/integrations"


async def test_state_is_single_use(fake_redis):
    """GETDEL makes the read-and-delete atomic, so a replayed callback finds nothing."""
    token = await issue_state(fake_redis, tenant_id=uuid.uuid4(), provider=GOOGLE_CALENDAR)
    assert await consume_state(fake_redis, token) is not None
    assert await consume_state(fake_redis, token) is None


async def test_state_unknown_token_returns_none(fake_redis):
    assert await consume_state(fake_redis, "never-issued") is None
    assert await consume_state(fake_redis, "") is None


async def test_state_has_a_ttl(fake_redis):
    token = await issue_state(fake_redis, tenant_id=uuid.uuid4(), provider=GOOGLE_CALENDAR)
    ttl = await fake_redis.ttl(state_key(token))
    assert 0 < ttl <= oauth.settings.google_oauth_state_ttl_seconds


async def test_state_ignores_corrupt_payload(fake_redis):
    await fake_redis.set(state_key("junk"), "not json")
    assert await consume_state(fake_redis, "junk") is None


# --- access-token cache ----------------------------------------------------------- #
async def test_token_cache_round_trip_and_ciphertext_at_rest(fake_redis):
    tenant_id = uuid.uuid4()
    await token_cache.cache_access_token(fake_redis, tenant_id, GOOGLE_CALENDAR, "at-123", 3600)

    raw = await fake_redis.get(token_cache.cache_key(tenant_id, GOOGLE_CALENDAR))
    assert raw != "at-123"  # encrypted, because dev Redis has no password
    assert decrypt_secret(raw) == "at-123"
    assert (
        await token_cache.get_cached_access_token(fake_redis, tenant_id, GOOGLE_CALENDAR)
        == "at-123"
    )


async def test_token_cache_expires_before_google_does(fake_redis):
    tenant_id = uuid.uuid4()
    await token_cache.cache_access_token(fake_redis, tenant_id, GOOGLE_SHEETS, "at", 3600)
    ttl = await fake_redis.ttl(token_cache.cache_key(tenant_id, GOOGLE_SHEETS))
    assert ttl <= 3600 - oauth.settings.google_token_cache_skew_seconds


async def test_token_cache_floors_ttl_for_short_lived_tokens(fake_redis):
    tenant_id = uuid.uuid4()
    await token_cache.cache_access_token(fake_redis, tenant_id, GOOGLE_SHEETS, "at", 10)
    ttl = await fake_redis.ttl(token_cache.cache_key(tenant_id, GOOGLE_SHEETS))
    assert ttl > 0  # never a negative/zero TTL, which would mean "delete now"


async def test_token_cache_treats_undecryptable_value_as_a_miss(fake_redis):
    """Survives a Fernet key rotation instead of failing every tool call."""
    tenant_id = uuid.uuid4()
    key = token_cache.cache_key(tenant_id, GOOGLE_CALENDAR)
    await fake_redis.set(key, "gAAAAA-not-a-valid-token")

    assert await token_cache.get_cached_access_token(fake_redis, tenant_id, GOOGLE_CALENDAR) is None
    assert await fake_redis.get(key) is None  # unusable entry dropped


async def test_invalidate_access_token_removes_it(fake_redis):
    tenant_id = uuid.uuid4()
    await token_cache.cache_access_token(fake_redis, tenant_id, GOOGLE_SHEETS, "at", 3600)
    await token_cache.invalidate_access_token(fake_redis, tenant_id, GOOGLE_SHEETS)
    assert (
        await token_cache.get_cached_access_token(fake_redis, tenant_id, GOOGLE_SHEETS) is None
    )
