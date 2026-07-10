"""Integration credential service + resolver (DESIGN.md §7).

Hermetic: no real Google client is built. We cover credential precedence,
config cleaning, service-account validation, and the readiness gate.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.security import decrypt_secret
from app.integrations import GOOGLE_CALENDAR, GOOGLE_SHEETS
from app.integrations.resolver import _service_account_info, ready_providers
from app.models.skill import Integration
from app.services import integrations as svc

_FAKE_KEY = json.dumps(
    {
        "type": "service_account",
        "client_email": "qonvo-bot@proj.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
        "project_id": "proj",
    }
)


def _db_capture(added: list) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: added.append(obj))
    return db


# --- validation ------------------------------------------------------------------ #
def test_validate_service_account_json_accepts_valid_key():
    svc.validate_service_account_json(_FAKE_KEY)  # no raise


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"type": "authorized_user", "client_email": "a", "private_key": "k"}),
        json.dumps({"type": "service_account"}),  # missing email/key
    ],
)
def test_validate_service_account_json_rejects_bad_keys(bad):
    with pytest.raises(ValueError):
        svc.validate_service_account_json(bad)


# --- config cleaning ------------------------------------------------------------- #
def test_clean_config_keeps_only_known_keys():
    cleaned = svc._clean_config(
        GOOGLE_CALENDAR,
        {"calendar_id": "c1", "timezone": "Asia/Karachi", "junk": "drop", "spreadsheet_id": "x"},
    )
    assert cleaned == {"calendar_id": "c1", "timezone": "Asia/Karachi"}


def test_clean_config_drops_blank_values():
    cleaned = svc._clean_config(GOOGLE_SHEETS, {"spreadsheet_id": "", "sheet_range": "Leads"})
    assert cleaned == {"sheet_range": "Leads"}


# --- credential precedence ------------------------------------------------------- #
def test_service_account_info_prefers_tenant_key(monkeypatch):
    from app.core.security import encrypt_secret

    integration = Integration(
        tenant_id=uuid.uuid4(), provider=GOOGLE_CALENDAR, config={}
    )
    integration.encrypted_credentials = encrypt_secret(_FAKE_KEY)
    monkeypatch.setattr("app.integrations.resolver.settings.google_service_account_json", None)

    info = _service_account_info(integration)
    assert info["client_email"] == "qonvo-bot@proj.iam.gserviceaccount.com"


def test_service_account_info_falls_back_to_system_default(monkeypatch):
    integration = Integration(tenant_id=uuid.uuid4(), provider=GOOGLE_SHEETS, config={})
    integration.encrypted_credentials = None
    monkeypatch.setattr(
        "app.integrations.resolver.settings.google_service_account_json", _FAKE_KEY
    )
    info = _service_account_info(integration)
    assert info["type"] == "service_account"


def test_service_account_info_none_when_no_key(monkeypatch):
    integration = Integration(tenant_id=uuid.uuid4(), provider=GOOGLE_SHEETS, config={})
    integration.encrypted_credentials = None
    monkeypatch.setattr("app.integrations.resolver.settings.google_service_account_json", None)
    assert _service_account_info(integration) is None


# --- upsert encrypts at rest ----------------------------------------------------- #
async def test_upsert_encrypts_service_account_key_and_cleans_config():
    added: list = []
    db = _db_capture(added)
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

    integration = await svc.upsert_integration(
        db,
        uuid.uuid4(),
        GOOGLE_CALENDAR,
        config={"calendar_id": "c1", "junk": "x"},
        service_account_json=_FAKE_KEY,
        enabled=True,
    )

    assert integration.config == {"calendar_id": "c1"}
    assert integration.encrypted_credentials  # ciphertext, not plaintext
    assert integration.encrypted_credentials != _FAKE_KEY
    assert decrypt_secret(integration.encrypted_credentials) == _FAKE_KEY


async def test_upsert_rejects_unsupported_provider():
    db = _db_capture([])
    with pytest.raises(svc.UnknownProviderError):
        await svc.upsert_integration(db, uuid.uuid4(), "salesforce")


# --- readiness gate -------------------------------------------------------------- #
async def test_ready_providers_requires_key_and_target(monkeypatch):
    monkeypatch.setattr("app.integrations.resolver.settings.google_service_account_json", None)

    class _Integ:
        def __init__(self, provider, config, creds):
            self.provider = provider
            self.config = config
            self.encrypted_credentials = creds

    rows = [
        _Integ(GOOGLE_CALENDAR, {"calendar_id": "c1"}, "cipher"),  # ready
        _Integ(GOOGLE_SHEETS, {"spreadsheet_id": "s1"}, None),  # no key → not ready
    ]
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)

    ready = await ready_providers(db, uuid.uuid4())
    assert ready == {GOOGLE_CALENDAR}


# --- sheets client tab validation (ping) ----------------------------------------- #
class _FakeSheetsService:
    def __init__(self, titles):
        self._titles = titles

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, includeGridData):  # noqa: N803 - google kwarg name
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


async def test_ready_providers_uses_system_default_key(monkeypatch):
    monkeypatch.setattr(
        "app.integrations.resolver.settings.google_service_account_json", _FAKE_KEY
    )

    class _Integ:
        provider = GOOGLE_SHEETS
        config = {"spreadsheet_id": "s1"}
        encrypted_credentials = None  # relies on system default

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [_Integ()]
    db.execute = AsyncMock(return_value=result)

    ready = await ready_providers(db, uuid.uuid4())
    assert ready == {GOOGLE_SHEETS}
