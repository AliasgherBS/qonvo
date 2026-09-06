"""Branded email templates + transport plumbing (no network)."""

from __future__ import annotations

from app.services import email as E
from app.services import email_templates as T

_GREEN = "#00d26a"


def _assert_branded(html: str, *, must_contain: str) -> None:
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "qonvo" in html  # wordmark
    assert _GREEN in html  # brand green
    assert must_contain in html


def test_welcome_template_has_text_html_and_cta():
    subject, text, html = T.welcome("Ali", "Glow Salon", "https://app.example/dash")
    assert "Welcome" in subject
    assert "Glow Salon" in text and "Glow Salon" in html
    _assert_branded(html, must_contain="https://app.example/dash")  # CTA url present


def test_password_reset_template():
    subject, text, html = T.password_reset("Ali", "https://app.example/reset?token=abc")
    assert "password" in subject.lower()
    assert "https://app.example/reset?token=abc" in text
    _assert_branded(html, must_contain="https://app.example/reset?token=abc")


def test_team_invite_template():
    subject, text, html = T.team_invite("Glow Salon", "staff", "https://app.example/accept?token=xyz")
    assert "Glow Salon" in subject
    assert "staff" in text and "staff" in html
    _assert_branded(html, must_contain="https://app.example/accept?token=xyz")


def test_owner_alert_wraps_text_in_shell():
    html = T.owner_alert("A customer needs a human", "Line one.\n\nReason: manager")
    _assert_branded(html, must_contain="A customer needs a human")
    assert "Reason: manager" in html


async def test_send_email_log_transport_returns_true(monkeypatch):
    # Default 'log' provider must never touch the network and always succeed.
    monkeypatch.setattr(E.settings, "email_provider", "log")
    assert await E.send_email("x@example.com", "Subj", "text body", html="<p>hi</p>") is True


# --- Reply-To ------------------------------------------------------------------ #
# Every Qonvo email is sent from a no-reply address on a sending subdomain that
# has no mailbox behind it. Without Reply-To, an owner who hits reply to an
# escalation is answering nothing: the mail leaves, and nobody receives it.
# docs/EMAIL-SETUP.md §4.3.


class _FakeSMTP:
    """Captures the message instead of sending it."""

    sent: list[object] = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        type(self).sent.append(msg)


def _smtp_capture(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(E.settings, "email_provider", "smtp")
    monkeypatch.setattr(E.settings, "email_smtp_host", "smtp.example.com")
    monkeypatch.setattr(E.settings, "email_smtp_port", 587)
    monkeypatch.setattr(E.settings, "email_smtp_user", None)
    monkeypatch.setattr(E.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


async def test_smtp_sets_reply_to_from_settings(monkeypatch):
    cap = _smtp_capture(monkeypatch)
    monkeypatch.setattr(E.settings, "email_reply_to", "support@qonvo.org")

    assert await E.send_email("owner@example.com", "Escalation", "body") is True
    assert cap.sent[0]["Reply-To"] == "support@qonvo.org"


async def test_smtp_omits_reply_to_when_unset(monkeypatch):
    """An empty Reply-To header is worse than none: some clients honour it and
    the reply goes nowhere at all."""
    cap = _smtp_capture(monkeypatch)
    monkeypatch.setattr(E.settings, "email_reply_to", None)

    assert await E.send_email("owner@example.com", "Escalation", "body") is True
    assert cap.sent[0]["Reply-To"] is None


async def test_explicit_reply_to_beats_the_setting(monkeypatch):
    cap = _smtp_capture(monkeypatch)
    monkeypatch.setattr(E.settings, "email_reply_to", "support@qonvo.org")

    await E.send_email("owner@example.com", "S", "b", reply_to="billing@qonvo.org")
    assert cap.sent[0]["Reply-To"] == "billing@qonvo.org"


async def test_resend_payload_carries_reply_to(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(json or {})
            return _Resp()

    monkeypatch.setattr(E.settings, "email_provider", "resend")
    monkeypatch.setattr(E.settings, "email_resend_api_key", "re_test")
    monkeypatch.setattr(E.settings, "email_reply_to", "support@qonvo.org")
    monkeypatch.setattr(E.httpx, "AsyncClient", _FakeClient)

    assert await E.send_email("owner@example.com", "S", "b") is True
    assert captured["reply_to"] == "support@qonvo.org"
