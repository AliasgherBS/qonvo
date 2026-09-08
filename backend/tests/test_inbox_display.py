"""How the inbox names a customer, and what the bell says (teardown I1, S4).

The bug these cover: the inbox showed the WhatsApp internal address verbatim as
the conversation title -- ``923009998877@c.us`` in the list and again in the
transcript header -- and nothing in the system ever captured the push name that
WhatsApp sends with every message, so there was nothing better to show. The
notification bell then quoted the model's own reasoning back at the owner and
did not say which customer it was about.

Pure unit tests on purpose: the display label is the thing that regressed, and
it needs no database to pin down.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.api.conversations import customer_display_name, format_phone_number
from app.api.notifications import first_sentence
from app.api.webhooks import extract_push_name
from app.models.conversation import Conversation
from app.workers.pipeline import InboundFragment, _get_or_create_conversation, push_name_from

# --------------------------------------------------------------------------- #
# Phone formatting
# --------------------------------------------------------------------------- #


def test_pakistani_mobile_is_grouped_readably():
    assert format_phone_number("923009998877@c.us") == "+92 300 999 8877"


def test_country_code_length_is_not_assumed():
    # One digit (NANP), two digits (Pakistan/UK), three digits (Malta).
    assert format_phone_number("14155552671@c.us") == "+1 415 555 2671"
    assert format_phone_number("447700900123@c.us") == "+44 770 090 0123"
    assert format_phone_number("35699001234@c.us") == "+356 9900 1234"


def test_no_group_is_ever_a_single_digit():
    for chat_id in ("923009998877@c.us", "14155552671@c.us", "8613800138000@c.us"):
        groups = format_phone_number(chat_id).split(" ")[1:]
        assert all(len(group) > 1 for group in groups), format_phone_number(chat_id)


def test_a_number_too_short_to_be_real_is_still_shown():
    # Test doubles and seeded rows use short numbers; they must not crash or
    # render as a plausible-looking international number.
    assert format_phone_number("123@c.us") == "+123"


# --------------------------------------------------------------------------- #
# The display label
# --------------------------------------------------------------------------- #


def test_push_name_wins_when_we_have_one():
    assert customer_display_name("923009998877@c.us", "Sara Khan") == "Sara Khan"
    assert customer_display_name("29918758989949@lid", "  Sara Khan  ") == "Sara Khan"


def test_number_is_formatted_when_there_is_no_name():
    assert customer_display_name("923009998877@c.us") == "+92 300 999 8877"
    assert customer_display_name("923009998877@c.us", "   ") == "+92 300 999 8877"


def test_a_linked_id_is_never_dressed_up_as_a_phone_number():
    # @lid is WhatsApp's Linked ID. Formatting it as a number would invent a
    # phone that does not exist and that an owner might try to call.
    label = customer_display_name("29918758989949@lid")
    assert not label.startswith("+")
    assert "9949" in label


def test_no_label_is_ever_a_raw_whatsapp_address():
    # The original bug, stated as an assertion.
    for chat_id in ("923009998877@c.us", "29918758989949@lid", "923001234567@s.whatsapp.net"):
        assert "@" not in customer_display_name(chat_id)


# --------------------------------------------------------------------------- #
# Push-name capture from the webhook payload
# --------------------------------------------------------------------------- #


def test_push_name_is_read_from_every_engine_spelling():
    # WEBJS nests notifyName under _data; NOWEB sends pushName at the top level.
    assert extract_push_name({"_data": {"notifyName": "Sara Khan"}}) == "Sara Khan"
    assert extract_push_name({"pushName": "Sara Khan"}) == "Sara Khan"
    assert extract_push_name({"notifyName": "Sara Khan"}) == "Sara Khan"
    assert extract_push_name({"_data": {"verifiedBizName": "Glow Salon"}}) == "Glow Salon"


def test_push_name_absent_or_useless_is_none():
    assert extract_push_name({}) is None
    assert extract_push_name({"pushName": ""}) is None
    assert extract_push_name({"pushName": "   "}) is None
    # Just the number again: the formatted number is better than this.
    assert extract_push_name({"pushName": "923009998877"}) is None
    # Not a string (a malformed payload must not raise inside the webhook).
    assert extract_push_name({"pushName": 923009998877}) is None
    assert extract_push_name({"_data": "not-a-dict"}) is None


def test_push_name_is_cleaned_and_fits_the_column():
    assert extract_push_name({"pushName": " Sara\n  Khan "}) == "Sara Khan"
    assert len(extract_push_name({"pushName": "x" * 400})) == 255


def test_push_name_from_fragments_prefers_the_latest():
    fragments = [
        InboundFragment(message_id="a", body="hi", push_name="Sara"),
        InboundFragment(message_id="b", body="there", push_name="Sara Khan"),
    ]
    assert push_name_from(fragments) == "Sara Khan"
    assert push_name_from([InboundFragment(message_id="c", body="hi")]) is None


# --------------------------------------------------------------------------- #
# Persisting it on the conversation
# --------------------------------------------------------------------------- #


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Just enough AsyncSession for ``_get_or_create_conversation``."""

    def __init__(self, existing=None):
        self.existing = existing
        self.added: list[object] = []

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self.existing)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


async def test_new_conversation_stores_the_push_name():
    db = _FakeSession()
    session_row = SimpleNamespace(id=uuid.uuid4())
    conversation = await _get_or_create_conversation(
        db, uuid.uuid4(), session_row, "923009998877@c.us", push_name="Sara Khan"
    )
    assert conversation.customer_name == "Sara Khan"


async def test_existing_conversation_picks_up_a_name_it_never_had():
    # Every conversation created before name capture existed has customer_name
    # NULL. If the name were only written at creation, those would stay nameless
    # forever -- which is every conversation a live tenant already has.
    existing = Conversation(chat_id="923009998877@c.us", customer_name=None)
    db = _FakeSession(existing)
    conversation = await _get_or_create_conversation(
        db, uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()), "923009998877@c.us",
        push_name="Sara Khan",
    )
    assert conversation is existing
    assert conversation.customer_name == "Sara Khan"


async def test_a_missing_push_name_does_not_erase_a_known_one():
    existing = Conversation(chat_id="923009998877@c.us", customer_name="Sara Khan")
    db = _FakeSession(existing)
    conversation = await _get_or_create_conversation(
        db, uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()), "923009998877@c.us", push_name=None
    )
    assert conversation.customer_name == "Sara Khan"


# --------------------------------------------------------------------------- #
# Notification bodies (S4)
# --------------------------------------------------------------------------- #


def test_the_models_self_justification_is_trimmed_away():
    reason = (
        "Customer requests a refund for a colour service that was ruined last "
        "week. This is a complaint/refund scenario, which requires a human "
        "handoff."
    )
    assert first_sentence(reason) == (
        "Customer requests a refund for a colour service that was ruined last week."
    )


def test_first_sentence_handles_urdu_and_empty_bodies():
    assert first_sentence("قیمت کیا ہے۔ یہ اہم ہے۔") == "قیمت کیا ہے۔"
    assert first_sentence(None) is None
    assert first_sentence("") is None
    assert first_sentence("   ") is None


def test_a_body_with_no_sentence_end_is_clipped_not_dropped():
    long_reason = "customer is upset " * 40
    summary = first_sentence(long_reason)
    assert summary is not None
    assert len(summary) <= 200
    assert summary.endswith("…")
