"""Chat-filtering rules (DESIGN.md §5.1)."""

from __future__ import annotations

import pytest
from app.api.webhooks import is_processable_chat_id


@pytest.mark.parametrize(
    "chat_id,expected",
    [
        ("14155550123@c.us", True),
        ("923001234567@c.us", True),
        # WhatsApp Linked IDs — modern accounts send 1:1 messages from @lid
        # (caught live: real sender arrived as 29918758989949@lid).
        ("29918758989949@lid", True),
        ("120363000000000000@g.us", False),  # group
        ("status@broadcast", False),  # status
        ("0123@newsletter", False),  # newsletter
        ("someone@broadcast", False),
        (None, False),
        ("", False),
        ("plainstring", False),
    ],
)
def test_is_processable_chat_id(chat_id, expected):
    assert is_processable_chat_id(chat_id) is expected
