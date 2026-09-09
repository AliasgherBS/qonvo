"""POST /api/behavior/instructions/review (functional test §04).

No provider, no database, no Redis server: the model is scripted, the session
is a stub and Redis is fakeredis. That is not only for speed. The owner has
limited credit and asked explicitly that paid probes not be run, and a feature
whose tests spend money is a feature nobody runs the tests for.

What is worth pinning here is the honesty of the failure paths. The route
charges the tenant's own key, so every way it can go wrong has to leave the
owner's instructions untouched and say which way it went wrong. Out of quota is
not hypothetical: two customer messages were already lost to a 429 "you
exceeded your current quota".
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from app.agent.instruction_review import MAX_INPUT_CHARS
from app.api import behavior_assist
from app.api.behavior_assist import INSTRUCTION_REVIEW
from app.api.deps import get_db, get_redis_dep, require_owner
from app.core.limits import MAX_CUSTOM_INSTRUCTIONS
from app.integrations import GOOGLE_CALENDAR
from app.integrations.resolver import STATE_OK
from app.main import app
from app.providers.base import LLMResult
from app.providers.openai_compat import ProviderError, ProviderTimeout
from httpx import ASGITransport, AsyncClient

TENANT = uuid.uuid4()
PATH = "/api/behavior/instructions/review"

ROMAN_URDU = "Many write Roman Urdu; reply in Roman Urdu when they do"
NO_DIARY = "Never say a time slot is free or booked. You cannot see any diary."
CALLBACK = (
    "Take the name and the number, then tell the customer a representative will "
    "call within a few hours to confirm."
)
LIVE_INSTRUCTIONS = f"{ROMAN_URDU}\n{NO_DIARY}\n{CALLBACK}"


# --- stubs ----------------------------------------------------------------------- #
class _Result:
    """Enough of a SQLAlchemy result for the two reads the route makes."""

    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return list(self._value or [])


class _Session:
    """Answers the config read, then the integrations read, in that order."""

    def __init__(self, config, integrations) -> None:
        self._queue = [_Result(config), _Result(integrations)]
        self.statements: list[object] = []

    async def execute(self, statement, *_a, **_kw):
        self.statements.append(statement)
        return self._queue.pop(0)


def _config(**overrides):
    base = {
        "business_name": "Depilex",
        "reply_language_mode": "match",
        "llm_provider": "gemini",
        "llm_model": "gemini-2.0-flash",
        "providers": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _calendar_row():
    """A connected Google Calendar, as ``credential_state`` reads it.

    Really encrypted, and carrying the scope the calendar actually requires.
    A hand-written "ciphertext" string reads as *missing*, which would have
    made every integration assertion in this file pass vacuously.
    """
    from app.core.security import encrypt_secret
    from app.integrations.scopes import CALENDAR_SCOPE

    return SimpleNamespace(
        provider=GOOGLE_CALENDAR,
        enabled=True,
        encrypted_credentials=encrypt_secret(json.dumps({"refresh_token": "1//fake"})),
        config={"granted_scopes": [CALENDAR_SCOPE], "calendar_id": "qonvo-bookings"},
    )


class _ScriptedLLM:
    """One answer per press, and it records the prompt it was handed."""

    def __init__(self, *, answer: str | None = None, raises: Exception | None = None) -> None:
        self.answer = answer
        self.raises = raises
        self.calls: list[list] = []
        self.closed = False

    async def generate(self, messages, *, tools=None, model=None):
        self.calls.append(list(messages))
        if self.raises is not None:
            raise self.raises
        return LLMResult(text=self.answer or "", prompt_tokens=900, completion_tokens=300)

    async def aclose(self) -> None:
        self.closed = True


class _SlowLLM(_ScriptedLLM):
    async def generate(self, messages, *, tools=None, model=None):
        await asyncio.sleep(5)
        raise AssertionError("should have timed out")  # pragma: no cover


def answer(improved: str, changes: list[dict] | None = None) -> str:
    return json.dumps({"improved": improved, "changes": changes or []})


GOOD_ANSWER = answer(
    "Take the name and the number, then say the team has been notified.",
    [
        {
            "kind": "removed",
            "summary": "Removed the Roman Urdu rule; your Reply language setting controls this.",
        },
        {
            "kind": "removed",
            "summary": "Removed 'you cannot see any diary'; Google Calendar is connected.",
        },
        {
            "kind": "tightened",
            "summary": "Dropped the promise that a representative will call.",
        },
    ],
)


@pytest.fixture
def context(monkeypatch, fake_redis):
    """The route with everything outside it replaced.

    ``_record_spend`` is left real, with ``record_billed_usage`` patched, so
    the metering call is exercised rather than skipped: this press costs the
    owner money and a test that stubbed the accounting would not notice it
    going missing.
    """
    state = SimpleNamespace(
        llm=_ScriptedLLM(answer=GOOD_ANSWER),
        session=_Session(_config(), [_calendar_row()]),
        usage=[],
    )

    async def _record(tenant_id, **kwargs):
        state.usage.append((tenant_id, kwargs))

    monkeypatch.setattr(behavior_assist, "resolve_llm", lambda config: state.llm)
    monkeypatch.setattr("app.workers.pipeline.record_billed_usage", _record)
    app.dependency_overrides[require_owner] = lambda: TENANT
    app.dependency_overrides[get_db] = lambda: state.session
    app.dependency_overrides[get_redis_dep] = lambda: fake_redis
    try:
        yield state
    finally:
        app.dependency_overrides.clear()


async def press(instructions: str = LIVE_INSTRUCTIONS):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(PATH, json={"instructions": instructions})


# --- the happy path -------------------------------------------------------------- #
async def test_a_press_returns_a_suggestion_and_a_list_of_changes(context):
    """The whole point of not auto-saving: an opaque rewrite is not
    reviewable, so the changes travel with it."""
    resp = await press()

    assert resp.status_code == 200
    body = resp.json()
    assert "Roman Urdu" not in body["improved"]
    assert "diary" not in body["improved"]
    assert "representative will" not in body["improved"]
    assert len(body["changes"]) == 3
    assert body["changes"][0]["kind"] == "removed"
    assert body["characters"] == len(body["improved"])
    assert body["limit"] == MAX_CUSTOM_INSTRUCTIONS
    assert body["unchanged"] is False


async def test_it_reviews_the_text_that_was_sent_not_the_saved_row(context):
    """The owner may be mid-edit. Reviewing the stale saved version would hand
    back a suggestion that does not match the textarea they are looking at."""
    await press("Always reply in English.")

    [system, user] = context.llm.calls[0]
    assert system.role == "system"
    assert "Always reply in English." in user.content


async def test_the_connected_calendar_reaches_the_prompt(context):
    """Read from our own integrations rows. Which integrations are connected is
    the difference between "you cannot see any diary" being a defect and it
    being a fact."""
    await press()

    [_system, user] = context.llm.calls[0]
    assert "Google Calendar" in user.content
    # The deterministic check fired, because the calendar is connected.
    assert "cannot see any diary" in user.content


async def test_nothing_connected_means_the_diary_line_is_not_flagged(monkeypatch, context):
    context.session = _Session(_config(), [])
    app.dependency_overrides[get_db] = lambda: context.session

    await press(NO_DIARY)

    [_system, user] = context.llm.calls[0]
    assert "Nothing is connected" in user.content
    assert "Automatic checks flagged" not in user.content


async def test_no_change_needed_is_a_first_class_answer(context):
    """"Your instructions look fine" is worth the press, and it is not an
    error."""
    text = "- Never quote a price. Say it depends on the branch."
    context.llm = _ScriptedLLM(answer=answer(text))

    resp = await press(text)

    assert resp.status_code == 200
    assert resp.json()["unchanged"] is True
    assert resp.json()["changes"] == []


async def test_one_press_is_one_call(context):
    """Budgeting. There is no retry loop here and no background invocation
    anywhere: the only thing that starts this is the owner pressing it."""
    await press()

    assert len(context.llm.calls) == 1
    assert context.llm.closed is True


async def test_the_tokens_are_recorded_against_the_tenant(context):
    """The provider billed the tenant's key the moment it answered, so leaving
    this out of usage would make the feature look free."""
    await press()

    [(tenant_id, kwargs)] = context.usage
    assert tenant_id == TENANT
    assert kwargs["tokens"] == 1200
    # No customer message was handled. Counting one would corrupt the
    # cost-per-conversation figure on the analytics page.
    assert kwargs["messages_in"] == 0
    assert kwargs["messages_out"] == 0


# --- refusals that cost nothing -------------------------------------------------- #
async def test_an_empty_field_is_refused_without_calling_the_model(context):
    resp = await press("   ")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "empty"
    assert context.llm.calls == []


async def test_an_oversized_field_is_refused_without_calling_the_model(context):
    resp = await press("x" * (MAX_INPUT_CHARS + 1))

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "too_long_to_review"
    assert context.llm.calls == []


# --- the rate limit -------------------------------------------------------------- #
async def test_the_press_is_rate_limited_per_tenant(context):
    """Per tenant, because the credit is the tenant's. Ten an hour covers the
    press-read-edit-press loop several times and bounds a stuck button."""
    for _ in range(INSTRUCTION_REVIEW.limit):
        context.session = _Session(_config(), [_calendar_row()])
        app.dependency_overrides[get_db] = lambda: context.session
        assert (await press()).status_code == 200

    context.session = _Session(_config(), [_calendar_row()])
    app.dependency_overrides[get_db] = lambda: context.session
    resp = await press()

    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "rate_limited"
    assert resp.headers["Retry-After"] == str(INSTRUCTION_REVIEW.window_seconds)
    # The eleventh press did not reach the provider.
    assert len(context.llm.calls) == INSTRUCTION_REVIEW.limit


# --- degrading honestly ---------------------------------------------------------- #
async def test_out_of_quota_says_so_and_changes_nothing(context):
    """This has actually happened. "Something went wrong" would send the owner
    to us rather than to their provider's billing page."""
    context.llm = _ScriptedLLM(
        raises=ProviderError("429: exceeded your current quota", status_code=429)
    )

    resp = await press()

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "llm_quota_exceeded"
    assert "quota" in detail["message"]
    assert "untouched" in detail["message"]


async def test_a_rejected_key_is_named_as_such(context):
    context.llm = _ScriptedLLM(raises=ProviderError("401: invalid api key", status_code=401))

    resp = await press()

    assert resp.json()["detail"]["code"] == "llm_auth_failed"


async def test_a_provider_outage_is_named_as_such(context):
    context.llm = _ScriptedLLM(raises=ProviderError("502: bad gateway", status_code=502))

    resp = await press()

    assert resp.json()["detail"]["code"] == "llm_unavailable"


async def test_the_adapters_own_timeout_is_reported_as_slowness(context):
    context.llm = _ScriptedLLM(raises=ProviderTimeout("timed out"))

    resp = await press()

    assert resp.json()["detail"]["code"] == "llm_timeout"


async def test_a_slow_provider_is_cut_off_rather_than_left_spinning(monkeypatch, context):
    """The adapter's own timeout plus retries can run past a minute, which is
    fine for a worker and not for somebody watching a button."""
    monkeypatch.setattr(behavior_assist, "REVIEW_TIMEOUT_SECONDS", 0.01)
    context.llm = _SlowLLM()

    resp = await press()

    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "llm_timeout"


async def test_an_unusable_answer_is_never_presented_as_a_suggestion(context):
    """A failed generation dressed up as a suggestion is the one thing this
    feature must not do."""
    context.llm = _ScriptedLLM(answer="Sure! Here is a better version for you.")

    resp = await press()

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "unusable_suggestion"


async def test_a_suggestion_over_the_cap_is_refused(context):
    """It could not be saved, so offering it would end in the owner pressing
    Save and being told no with their original already gone."""
    context.llm = _ScriptedLLM(answer=answer("x" * (MAX_CUSTOM_INSTRUCTIONS + 50)))

    resp = await press()

    assert resp.status_code == 502
    assert "characters" in resp.json()["detail"]["message"]


# --- authorization --------------------------------------------------------------- #
async def test_the_route_is_owner_only():
    """Custom instructions are what the rep tells customers, which is the line
    ``require_owner`` draws. No token at all here, so the real dependency
    answers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(PATH, json={"instructions": "anything"})

    assert resp.status_code == 401


def test_the_calendar_row_stub_matches_what_the_route_calls_connected():
    """Guards the stub itself: if ``credential_state`` stopped seeing this row
    as connected, every integration assertion above would pass vacuously."""
    from app.integrations.resolver import credential_state

    assert credential_state(_calendar_row()) == STATE_OK
