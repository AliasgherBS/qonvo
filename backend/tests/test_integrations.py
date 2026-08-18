"""Integration credential service + resolver (DESIGN.md §7).

Hermetic: no real Google client is built and no network is touched. Covers the
credential-state machine, what does and doesn't get encrypted, the readiness gate
that keeps unusable skills out of the model's tool list, and the guarded revoke.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.security import decrypt_secret, encrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from app.integrations.google_oauth import GoogleReauthRequired, TokenBundle
from app.integrations.resolver import (
    STATE_MISSING,
    STATE_OK,
    STATE_REAUTH_REQUIRED,
    STATE_SCOPE_UPGRADE_REQUIRED,
    ReauthRequiredError,
    access_token_for,
    credential_state,
    oauth_bundle,
    ready_providers,
)
from app.integrations.scopes import CALENDAR_SCOPE, SHEETS_SCOPE
from app.models.skill import Integration
from app.services import integrations as svc

# A pre-OAuth service-account blob. Must read as "not connected" so legacy rows
# retire themselves without a data migration.
_LEGACY_SA_KEY = json.dumps(
    {
        "type": "service_account",
        "client_email": "qonvo-bot@proj.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
    }
)


def _db_capture(added: list) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: added.append(obj))
    return db


def _integration(
    provider: str = GOOGLE_CALENDAR,
    *,
    refresh_token: str | None = "1//rt",
    config: dict | None = None,
) -> Integration:
    integration = Integration(tenant_id=uuid.uuid4(), provider=provider, config=config or {})
    integration.enabled = True
    integration.encrypted_credentials = (
        encrypt_secret(json.dumps({"refresh_token": refresh_token})) if refresh_token else None
    )
    return integration


def _ok_config(scope: str = CALENDAR_SCOPE, **extra) -> dict:
    return {"granted_scopes": [scope], **extra}


# --- config cleaning ------------------------------------------------------------- #
def test_clean_config_keeps_only_owner_writable_keys():
    """calendar_id is provisioned by Qonvo, so an owner PUT must not set it."""
    cleaned = svc._clean_config(
        GOOGLE_CALENDAR,
        {"calendar_id": "c1", "timezone": "Asia/Karachi", "junk": "drop"},
    )
    assert cleaned == {"timezone": "Asia/Karachi"}


def test_clean_config_drops_blank_values():
    cleaned = svc._clean_config(GOOGLE_SHEETS, {"spreadsheet_id": "", "sheet_range": "Leads"})
    assert cleaned == {"sheet_range": "Leads"}


def test_upsert_merges_config_instead_of_replacing():
    """A PUT of just `timezone` must not wipe the system-written target id."""
    integration = _integration(config={"calendar_id": "c1", "granted_scopes": [CALENDAR_SCOPE]})
    svc._merge_config(integration, {"timezone": "Asia/Karachi"})
    assert integration.config["calendar_id"] == "c1"
    assert integration.config["granted_scopes"] == [CALENDAR_SCOPE]
    assert integration.config["timezone"] == "Asia/Karachi"


# --- credential state machine ---------------------------------------------------- #
def test_credential_state_missing_without_credentials():
    assert credential_state(_integration(refresh_token=None)) == STATE_MISSING
    assert credential_state(None) == STATE_MISSING


def test_legacy_service_account_blob_reads_as_missing():
    """Pre-OAuth rows retire themselves — no migration, owner just clicks Connect."""
    integration = _integration(refresh_token=None)
    integration.encrypted_credentials = encrypt_secret(_LEGACY_SA_KEY)
    assert oauth_bundle(integration) is None
    assert credential_state(integration) == STATE_MISSING


def test_credential_state_reauth_required_when_flagged():
    integration = _integration(config=_ok_config(needs_reauth=True))
    assert credential_state(integration) == STATE_REAUTH_REQUIRED


def test_credential_state_scope_upgrade_when_required_scope_absent():
    integration = _integration(config={"granted_scopes": ["openid", "email"]})
    assert credential_state(integration) == STATE_SCOPE_UPGRADE_REQUIRED


def test_credential_state_ok_with_required_scope():
    assert credential_state(_integration(config=_ok_config())) == STATE_OK


def test_partial_consent_on_freebusy_does_not_break_calendar():
    """freebusy only degrades availability accuracy — it must not brick the grant."""
    assert credential_state(_integration(config=_ok_config())) == STATE_OK


# --- what gets encrypted, and what must not -------------------------------------- #
async def test_store_oauth_credentials_encrypts_only_the_refresh_token():
    added: list = []
    db = _db_capture(added)
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

    integration = await svc.store_oauth_credentials(
        db,
        uuid.uuid4(),
        GOOGLE_CALENDAR,
        refresh_token="1//secret-rt",
        granted_scopes=[CALENDAR_SCOPE, "openid"],
        account_email="owner@example.com",
    )

    blob = integration.encrypted_credentials
    assert blob and blob != "1//secret-rt"  # ciphertext, not plaintext
    stored = json.loads(decrypt_secret(blob))
    assert stored == {"refresh_token": "1//secret-rt"}
    # Platform-wide credentials must never be duplicated per row, or rotating the
    # client secret becomes a re-encrypt-every-tenant migration.
    assert "client_secret" not in stored
    assert "client_id" not in stored
    # Non-secrets belong in config so listing never has to decrypt.
    assert integration.config["granted_scopes"] == [CALENDAR_SCOPE, "openid"]
    assert integration.config["account_email"] == "owner@example.com"
    assert integration.config["connected_at"]
    assert integration.enabled is True


async def test_store_oauth_credentials_clears_needs_reauth():
    added: list = []
    existing = _integration(config=_ok_config(needs_reauth=True, needs_reauth_at="then"))
    db = _db_capture(added)
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: existing))

    integration = await svc.store_oauth_credentials(
        db,
        existing.tenant_id,
        GOOGLE_CALENDAR,
        refresh_token="1//new",
        granted_scopes=[CALENDAR_SCOPE],
        account_email=None,
    )
    assert "needs_reauth" not in integration.config
    assert "needs_reauth_at" not in integration.config
    assert credential_state(integration) == STATE_OK


async def test_upsert_rejects_unsupported_provider():
    db = _db_capture([])
    with pytest.raises(svc.UnknownProviderError):
        await svc.upsert_integration(db, uuid.uuid4(), "salesforce")


def test_sanitized_never_leaks_secrets():
    integration = _integration(config=_ok_config(calendar_id="c1", account_email="o@e.com"))
    out = svc.sanitized(integration)
    blob = json.dumps(out)
    assert "refresh_token" not in blob
    assert "encrypted_credentials" not in blob
    assert integration.encrypted_credentials not in blob
    assert out["connected"] is True
    assert out["status"] == STATE_OK
    assert out["account_email"] == "o@e.com"


def test_sanitized_not_connected_without_target_id():
    """A live grant with nothing provisioned yet is not "connected"."""
    out = svc.sanitized(_integration(config=_ok_config()))
    assert out["status"] == STATE_OK
    assert out["connected"] is False


# --- readiness gate -------------------------------------------------------------- #
def _rows_db(rows: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


async def test_ready_providers_requires_grant_and_target():
    rows = [
        _integration(GOOGLE_CALENDAR, config=_ok_config(calendar_id="c1")),  # ready
        # live grant but nothing picked yet → not ready
        _integration(GOOGLE_SHEETS, config=_ok_config(SHEETS_SCOPE)),
    ]
    ready = await ready_providers(_rows_db(rows), uuid.uuid4())
    assert ready == {GOOGLE_CALENDAR}


async def test_ready_providers_excludes_reauth_required():
    rows = [
        _integration(GOOGLE_CALENDAR, config=_ok_config(calendar_id="c1", needs_reauth=True))
    ]
    assert await ready_providers(_rows_db(rows), uuid.uuid4()) == set()


async def test_ready_providers_excludes_scope_mismatch():
    rows = [
        _integration(
            GOOGLE_SHEETS,
            config={"granted_scopes": ["openid"], "spreadsheet_id": "s1"},
        )
    ]
    assert await ready_providers(_rows_db(rows), uuid.uuid4()) == set()


async def test_ready_providers_excludes_missing_credentials():
    rows = [_integration(GOOGLE_SHEETS, refresh_token=None, config={"spreadsheet_id": "s1"})]
    assert await ready_providers(_rows_db(rows), uuid.uuid4()) == set()


# --- access token minting -------------------------------------------------------- #
async def test_access_token_cache_hit_does_not_refresh(fake_redis, monkeypatch):
    from app.integrations import token_cache

    integration = _integration(config=_ok_config(calendar_id="c1"))
    tenant_id = integration.tenant_id
    await token_cache.cache_access_token(
        fake_redis, tenant_id, GOOGLE_CALENDAR, "cached-at", 3600
    )

    calls = []

    async def _never(*_a, **_k):
        calls.append(1)
        raise AssertionError("refresh must not be called on a cache hit")

    monkeypatch.setattr("app.integrations.resolver.refresh_access_token", _never)

    token = await access_token_for(AsyncMock(), tenant_id, integration, redis=fake_redis)
    assert token == "cached-at"
    assert calls == []


async def test_access_token_miss_refreshes_once_and_caches(fake_redis, monkeypatch):
    from app.integrations import token_cache

    integration = _integration(config=_ok_config(calendar_id="c1"))
    tenant_id = integration.tenant_id
    calls: list[str] = []

    async def _refresh(refresh_token, **_k):
        calls.append(refresh_token)
        return TokenBundle(
            access_token="fresh-at",
            expires_in=3600,
            refresh_token=None,
            granted_scopes=(CALENDAR_SCOPE,),
            account_email=None,
        )

    monkeypatch.setattr("app.integrations.resolver.refresh_access_token", _refresh)

    token = await access_token_for(AsyncMock(), tenant_id, integration, redis=fake_redis)
    assert token == "fresh-at"
    assert calls == ["1//rt"]
    assert (
        await token_cache.get_cached_access_token(fake_redis, tenant_id, GOOGLE_CALENDAR)
        == "fresh-at"
    )


async def test_access_token_marks_needs_reauth_on_invalid_grant(fake_redis, monkeypatch):
    integration = _integration(config=_ok_config(calendar_id="c1"))
    tenant_id = integration.tenant_id

    async def _dead(*_a, **_k):
        raise GoogleReauthRequired("invalid_grant: Token has been expired or revoked.")

    marked: list[tuple] = []

    async def _mark(_db, tid, provider):
        marked.append((tid, provider))
        # Mirror the real write so the state machine flips.
        integration.config = {**(integration.config or {}), "needs_reauth": True}

    monkeypatch.setattr("app.integrations.resolver.refresh_access_token", _dead)
    monkeypatch.setattr("app.services.integrations.mark_needs_reauth", _mark)

    with pytest.raises(ReauthRequiredError):
        await access_token_for(AsyncMock(), tenant_id, integration, redis=fake_redis)

    assert marked == [(tenant_id, GOOGLE_CALENDAR)]
    # The next turn's gate must now drop this provider's skills.
    assert credential_state(integration) == STATE_REAUTH_REQUIRED


async def test_resolve_integration_client_swallows_reauth(monkeypatch):
    """Handlers get None (their "not connected" branch), never a raw invalid_grant."""
    from app.integrations import resolver

    async def _boom(*_a, **_k):
        raise ReauthRequiredError("dead grant")

    async def _no_alert(*_a, **_k):
        return None

    monkeypatch.setattr(resolver, "build_calendar_client", _boom)
    monkeypatch.setattr(resolver, "_alert_owner_reauth", _no_alert)

    ctx = MagicMock(db=AsyncMock(), tenant_id=uuid.uuid4(), integration_clients=None)
    assert await resolver.resolve_integration_client(ctx, GOOGLE_CALENDAR) is None


async def test_injected_client_short_circuits_before_any_credential_work():
    from app.integrations import resolver

    sentinel = object()
    ctx = MagicMock(
        db=AsyncMock(),
        tenant_id=uuid.uuid4(),
        integration_clients={GOOGLE_CALENDAR: sentinel},
    )
    assert await resolver.resolve_integration_client(ctx, GOOGLE_CALENDAR) is sentinel


# --- disconnect / revoke guard --------------------------------------------------- #
async def test_delete_revokes_when_it_is_the_only_grant(monkeypatch):
    integration = _integration(GOOGLE_SHEETS, config=_ok_config(SHEETS_SCOPE))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: integration))
    db.delete = AsyncMock()

    revoked: list[str] = []

    async def _revoke(token, **_k):
        revoked.append(token)
        return True

    monkeypatch.setattr("app.integrations.google_oauth.revoke", _revoke)
    monkeypatch.setattr(svc, "other_google_provider_has_token", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "app.integrations.token_cache.invalidate_access_token", AsyncMock()
    )
    monkeypatch.setattr("app.core.redis.get_redis", MagicMock())

    assert await svc.delete_integration(db, integration.tenant_id, GOOGLE_SHEETS) is True
    assert revoked == ["1//rt"]
    db.delete.assert_awaited_once()


async def test_delete_skips_revoke_when_sibling_shares_the_grant(monkeypatch):
    """Google's /revoke kills the whole grant — revoking Sheets would break Calendar."""
    integration = _integration(GOOGLE_SHEETS, config=_ok_config(SHEETS_SCOPE))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: integration))
    db.delete = AsyncMock()

    revoked: list[str] = []

    async def _revoke(token, **_k):
        revoked.append(token)
        return True

    monkeypatch.setattr("app.integrations.google_oauth.revoke", _revoke)
    monkeypatch.setattr(svc, "other_google_provider_has_token", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.integrations.token_cache.invalidate_access_token", AsyncMock()
    )
    monkeypatch.setattr("app.core.redis.get_redis", MagicMock())

    assert await svc.delete_integration(db, integration.tenant_id, GOOGLE_SHEETS) is True
    assert revoked == []
    db.delete.assert_awaited_once()


async def test_delete_still_removes_row_when_revoke_fails(monkeypatch):
    """The owner asked Qonvo to stop acting; a Google outage must not block that."""
    integration = _integration(GOOGLE_SHEETS, config=_ok_config(SHEETS_SCOPE))
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: integration))
    db.delete = AsyncMock()

    monkeypatch.setattr("app.integrations.google_oauth.revoke", AsyncMock(return_value=False))
    monkeypatch.setattr(svc, "other_google_provider_has_token", AsyncMock(return_value=False))
    monkeypatch.setattr(
        "app.integrations.token_cache.invalidate_access_token", AsyncMock()
    )
    monkeypatch.setattr("app.core.redis.get_redis", MagicMock())

    assert await svc.delete_integration(db, integration.tenant_id, GOOGLE_SHEETS) is True
    db.delete.assert_awaited_once()


# --- sheet target selection ------------------------------------------------------- #
async def test_set_sheet_target_defaults_range_to_first_real_tab():
    """Not "Sheet1": a picked sheet may have renamed tabs, and a wrong default only
    surfaces as "Unable to parse range" at the first append."""
    integration = _integration(GOOGLE_SHEETS, config=_ok_config(SHEETS_SCOPE))
    db = AsyncMock()
    await svc.set_sheet_target(
        db, integration, spreadsheet_id="s1", title="Bookings", tabs=["Leads", "Orders"]
    )
    assert integration.config["spreadsheet_id"] == "s1"
    assert integration.config["sheet_range"] == "Leads"
    assert integration.config["available_tabs"] == ["Leads", "Orders"]


# --- sheets client tab validation (ping) ----------------------------------------- #
class _FakeSheetsService:
    def __init__(self, titles):
        self._titles = titles

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, includeGridData, fields=None):  # noqa: N803 - google kwarg
        self._resp = {"sheets": [{"properties": {"title": t}} for t in self._titles]}
        return self

    def execute(self):
        return self._resp


async def test_sheets_ping_rejects_missing_tab():
    from app.integrations.sheets import GoogleSheetsClient

    client = GoogleSheetsClient(
        _FakeSheetsService(["Hook Master Sheet", "Decode Kait"]), "sid", sheet_range="Sheet1"
    )
    with pytest.raises(ValueError, match="not found"):
        await client.ping()


async def test_sheets_ping_accepts_existing_tab_with_a1_range():
    from app.integrations.sheets import GoogleSheetsClient

    client = GoogleSheetsClient(_FakeSheetsService(["Leads"]), "sid", sheet_range="Leads!A:D")
    await client.ping()  # no raise


async def test_sheets_list_tabs_returns_titles():
    from app.integrations.sheets import GoogleSheetsClient

    client = GoogleSheetsClient(_FakeSheetsService(["Leads", "Orders"]), "sid")
    assert await client.list_tabs() == ["Leads", "Orders"]
