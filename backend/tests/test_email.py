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
