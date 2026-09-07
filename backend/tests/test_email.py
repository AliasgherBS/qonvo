"""Branded email templates + transport plumbing (no network)."""

from __future__ import annotations

import pytest
from app.services import email as E
from app.services import email_templates as T

#: The five exact brand colours, the same set dashboard/scripts/verify-brand.mjs
#: enforces. Hardcoded here on purpose rather than imported from the module under
#: test: importing them would make this assertion vacuous, since any drift would
#: move both sides together. The emails were previously a near-miss palette that
#: nothing caught, because that gate only walks the dashboard tree.
BRAND = {
    "Signal Green": "#00C776",
    "Volt": "#C6FF3D",
    "Deep Forest": "#0B3B2B",
    "Ink": "#08130E",
    "Paper": "#F3EFE6",
}


def _assert_branded(html: str, *, must_contain: str) -> None:
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "qonvo" in html  # wordmark
    assert BRAND["Signal Green"] in html
    assert must_contain in html


def test_welcome_template_has_text_html_and_cta():
    subject, text, html = T.welcome("Ali", "Glow Salon", "https://app.example/dash")
    # The subject names the business rather than saying "Welcome": it competes
    # with every other welcome email in the inbox, and the business name is the
    # only part that is about the reader.
    assert "Glow Salon" in subject
    assert "Glow Salon" in text and "Glow Salon" in html
    _assert_branded(html, must_contain="https://app.example/dash")  # CTA url present


def test_welcome_says_what_the_product_actually_does():
    """"AI WhatsApp rep" tells a new owner nothing. The capabilities are the
    reason they signed up and the reason they will finish setting it up."""
    _, text, html = T.welcome("Ali", "Glow Salon", "https://app.example/dash")

    for phrase in ("voice note", "language", "hands the conversation"):
        assert phrase in html.lower(), phrase
    assert "Connect your WhatsApp number" in text  # the plain-text part carries it too


def test_welcome_quotas_come_from_the_plan_catalogue():
    """plans.py exists so a quota lives in one place. An email promising a
    number nobody sells would be that catalogue failing at its only job."""
    from app.billing.plans import PLANS, TRIAL_PLAN

    _, text, html = T.welcome(None, "Glow Salon", "https://app.example/dash")

    trial = PLANS[TRIAL_PLAN].entitlements["monthly_message_quota"]
    assert f"{trial:,}" in html and f"{trial:,}" in text
    for key, plan in PLANS.items():
        if key == TRIAL_PLAN:
            continue
        assert f"{plan.entitlements['monthly_message_quota']:,}" in html, key


def test_welcome_trial_length_is_not_retyped():
    """The email used to say "14-day" as a string. Change the constant and it
    would have started lying, silently, to every new customer."""
    from app.services.auth import TRIAL_DAYS

    _, text, html = T.welcome(None, "Glow Salon", "https://app.example/dash")
    assert f"{TRIAL_DAYS} days free" in html
    assert f"{TRIAL_DAYS}-day free trial" in text


def test_welcome_points_at_billing_without_quoting_a_price():
    """Prices live with the merchant of record, never in this repo, so the
    nudge is about what you get, and the number comes from the provider."""
    _, text, html = T.welcome(None, "Glow Salon", "https://app.example/dash")

    assert "https://app.example/dash/billing" in html
    assert "https://app.example/dash/billing" in text
    for currency in ("$", "USD", "PKR", "\u00a3", "\u20ac"):
        assert currency not in html, f"a price leaked into the welcome email: {currency}"


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


# --- consistency across all four emails ---------------------------------------- #
# The ask was a cohesive set, not four emails that each look fine alone. These
# assert the shared rules rather than any one template.
def _every_html() -> dict[str, str]:
    return {
        "welcome": T.welcome("Ali", "Glow Salon", "https://app.example/dash")[2],
        "password_reset": T.password_reset("Ali", "https://app.example/reset?t=a")[2],
        "team_invite": T.team_invite("Glow Salon", "staff", "https://app.example/accept?t=b")[2],
        "owner_alert": T.owner_alert("A customer needs a human", "Reason: manager"),
    }


@pytest.mark.parametrize("name,html", list(_every_html().items()))
def test_every_email_uses_the_exact_brand_palette(name, html):
    assert BRAND["Signal Green"] in html, name
    assert BRAND["Deep Forest"] in html, name
    assert BRAND["Ink"] in html, name
    assert BRAND["Paper"] in html, name


@pytest.mark.parametrize("name,html", list(_every_html().items()))
def test_no_sixth_colour_creeps_in(name, html):
    """Brand rule: the five colours are exact, nothing introduces a sixth. The
    only other hexes allowed are white and the documented neutrals, which are
    Ink composited over the surface behind it rather than invented greys."""
    import re

    allowed = {c.lower() for c in BRAND.values()} | {
        "#ffffff",
        T._BODY.lower(),
        T._MUTED.lower(),
        T._MUTED_ON_PAPER.lower(),
        T._HAIRLINE.lower(),
    }
    found = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}", html)}
    assert found <= allowed, f"{name}: unexpected {sorted(found - allowed)}"


@pytest.mark.parametrize("name,html", list(_every_html().items()))
def test_volt_is_a_spotlight_not_a_background(name, html):
    """The brand kit's words. Once per piece, at most, and never as a fill."""
    assert html.count(BRAND["Volt"]) <= 1, name
    assert f"background:{BRAND['Volt']}" not in html, name


@pytest.mark.parametrize("name,html", list(_every_html().items()))
def test_no_em_or_en_dashes_in_email_copy(name, html):
    """Same house rule the dashboard enforces in CI. That gate only walks the
    dashboard tree, so these emails drifted for months without anyone noticing."""
    assert "—" not in html, name
    assert "–" not in html, name


@pytest.mark.parametrize("name,html", list(_every_html().items()))
def test_layout_survives_real_email_clients(name, html):
    """Gmail and Outlook strip <style> blocks and ignore flexbox and grid, so a
    template that looks right in a browser can arrive as a column of unstyled
    text. Table plus inline styles is the only thing that survives."""
    assert "<style" not in html, name
    assert "display:flex" not in html, name
    assert "display:grid" not in html, name
    assert 'role="presentation"' in html, name
    # No remote images: clients block them by default, and a blocked logo leaves
    # a broken box where the brand should be.
    assert "<img" not in html, name


@pytest.mark.parametrize("name,html", list(_every_html().items()))
def test_every_email_has_a_preheader(name, html):
    """The grey line after the subject in an inbox list. Without one the client
    picks it, and it picks the first text it finds."""
    assert 'style="display:none;max-height:0;' in html, name
