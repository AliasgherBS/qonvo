"""Branded HTML email templates (transactional).

Every email ships as **multipart/alternative**: a plain-text part (deliverability
plus clients that block HTML) and this branded HTML part. The Qonvo mark is
rendered in HTML/CSS rather than a hosted image on purpose: most email clients
block remote images by default, so a CSS mark always renders and a logo file
would leave a broken box in its place.

Table-based layout with fully inline styles is the only thing that survives
Gmail, Outlook and Apple Mail intact. No flexbox, no grid, no <style> block,
no web fonts.

**Colours are the real brand palette**, matching dashboard/app/globals.css and
the five exact values dashboard/scripts/verify-brand.mjs enforces. They used to
be a near-miss set (a different green, a different paper) that nothing checked,
because that gate only walks the dashboard tree. An email is often the first
thing a customer sees from a company, so it being subtly off-brand is worse
here than almost anywhere else in the product.
"""

from __future__ import annotations

from app.billing.plans import PLANS, TRIAL_PLAN
from app.services.auth import TRIAL_DAYS

# --- The five brand colours, exact (globals.css) --------------------------- #
SIGNAL_GREEN = "#00C776"  # actions and highlights
VOLT = "#C6FF3D"  # accent. A spotlight, not a background: once per email
DEEP_FOREST = "#0B3B2B"  # dark surface
INK = "#08130E"  # headings, dark ground
PAPER = "#F3EFE6"  # light ground

# --- Derived neutrals ------------------------------------------------------ #
# Email cannot use color-mix(), so these are literal. They are Ink composited
# over the surface they sit on rather than invented greys, which is what keeps
# "the five colours are exact" true instead of merely claimed.
_BODY = "#343D39"  # 82% Ink on white
_MUTED = "#707673"  # 58% Ink on white
_MUTED_ON_PAPER = "#6B6F69"  # 58% Ink on Paper
_HAIRLINE = "#E7E1D4"  # Paper-dim, already a token in globals.css

_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

__all__ = [
    "DEEP_FOREST",
    "INK",
    "PAPER",
    "SIGNAL_GREEN",
    "VOLT",
    "owner_alert",
    "password_reset",
    "shell",
    "team_invite",
    "welcome",
]


# --------------------------------------------------------------------------- #
# Pieces
# --------------------------------------------------------------------------- #
def _p(text: str, *, size: int = 15, color: str = _BODY, top: int = 0) -> str:
    return (
        f'<p style="margin:{top}px 0 14px;font-family:{_FONT};font-size:{size}px;'
        f'line-height:1.62;color:{color};">{text}</p>'
    )


def _button(label: str, url: str) -> str:
    """Signal Green pill. Bulletproof enough: a table cell with a background,
    so a client that drops the anchor styling still shows a green block."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:28px 0 4px;"><tr>'
        f'<td style="background:{SIGNAL_GREEN};border-radius:12px;">'
        f'<a href="{url}" target="_blank" '
        f'style="display:inline-block;padding:15px 32px;font-family:{_FONT};'
        f"font-weight:700;font-size:15px;letter-spacing:-0.01em;color:{INK};"
        f'text-decoration:none;">{label}</a>'
        "</td></tr></table>"
    )


def _feature_rows(items: list[tuple[str, str]]) -> str:
    """What the product does, one line each. A check mark in Signal Green rather
    than an image, for the same reason the logo is CSS."""
    rows = "".join(
        f"<tr>"
        f'<td valign="top" style="width:26px;padding:7px 0;font-family:{_FONT};'
        f'font-size:15px;font-weight:800;color:{SIGNAL_GREEN};line-height:1.5;">&#10003;</td>'
        f'<td style="padding:7px 0;font-family:{_FONT};font-size:15px;line-height:1.5;color:{_BODY};">'
        f"<strong style=\"color:{INK};\">{title}</strong> {rest}</td>"
        f"</tr>"
        for title, rest in items
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:6px 0 4px;">{rows}</table>'
    )


def _numbered_steps(steps: list[str]) -> str:
    rows = "".join(
        f"<tr>"
        f'<td valign="top" style="width:34px;padding:7px 0;">'
        f'<span style="display:inline-block;width:24px;height:24px;line-height:24px;'
        f"background:{PAPER};border-radius:12px;text-align:center;font-family:{_FONT};"
        f'font-weight:800;color:{DEEP_FOREST};font-size:13px;">{i}</span></td>'
        f'<td style="padding:7px 0;font-family:{_FONT};font-size:15px;line-height:1.5;color:{_BODY};">{s}</td>'
        f"</tr>"
        for i, s in enumerate(steps, start=1)
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:4px 0 2px;">{rows}</table>'
    )


def _volt_note(heading: str, body: str) -> str:
    """The one Volt moment. The brand kit calls it a spotlight, not a
    background, so it is a 3px edge rather than a filled panel."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;margin:26px 0 2px;"><tr>'
        f'<td style="border-left:3px solid {VOLT};padding:2px 0 2px 16px;">'
        f'<p style="margin:0 0 5px;font-family:{_FONT};font-size:13px;font-weight:800;'
        f'letter-spacing:0.04em;text-transform:uppercase;color:{INK};">{heading}</p>'
        f'<p style="margin:0;font-family:{_FONT};font-size:14px;line-height:1.6;color:{_BODY};">{body}</p>'
        "</td></tr></table>"
    )


def _divider() -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;">'
        f'<tr><td style="border-top:1px solid {_HAIRLINE};font-size:0;line-height:0;'
        f'height:1px;padding:26px 0 0;">&nbsp;</td></tr></table>'
    )


def shell(
    *,
    preheader: str,
    heading: str,
    body_html: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
    eyebrow: str | None = None,
) -> str:
    """Wrap body content in the branded Qonvo shell.

    The header is a Deep Forest band rather than the page ground. It gives the
    mark somewhere to sit, and it is the cheapest way to make an email look
    designed rather than generated in an inbox full of white rectangles.
    """
    cta = _button(cta_label, cta_url) if cta_label and cta_url else ""
    # A raw link under the button as well: buttons get stripped, links do not.
    raw_link = (
        f'<p style="margin:16px 0 0;font-family:{_FONT};font-size:12px;line-height:1.55;'
        f'color:{_MUTED};">Or paste this link into your browser:<br>'
        f'<a href="{cta_url}" target="_blank" style="color:{DEEP_FOREST};'
        f'word-break:break-all;">{cta_url}</a></p>'
        if cta_url
        else ""
    )
    footer = (
        f'<p style="margin:0 0 8px;font-family:{_FONT};font-size:12px;line-height:1.55;'
        f'color:{_MUTED_ON_PAPER};">{footer_note}</p>'
        if footer_note
        else ""
    )
    eyebrow_html = (
        f'<p style="margin:0 0 10px;font-family:{_FONT};font-size:12px;font-weight:800;'
        f'letter-spacing:0.08em;text-transform:uppercase;color:{SIGNAL_GREEN};">{eyebrow}</p>'
        if eyebrow
        else ""
    )
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{heading}</title>
</head>
<body style="margin:0;padding:0;background:{PAPER};-webkit-font-smoothing:antialiased;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAPER};">
<tr><td align="center" style="padding:30px 12px 34px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">

<tr><td style="background:{DEEP_FOREST};border-radius:16px 16px 0 0;padding:22px 34px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="background:{SIGNAL_GREEN};border-radius:9px;height:32px;width:32px;text-align:center;vertical-align:middle;font-family:{_FONT};font-weight:800;font-size:17px;color:{INK};">Q</td>
<td style="padding-left:10px;font-family:{_FONT};font-weight:800;font-size:19px;letter-spacing:-0.02em;color:{PAPER};">qonvo</td>
</tr></table>
</td></tr>

<tr><td style="background:#ffffff;border:1px solid {_HAIRLINE};border-top:0;border-radius:0 0 16px 16px;padding:34px 34px 32px;">
{eyebrow_html}
<h1 style="margin:0 0 16px;font-family:{_FONT};font-size:25px;font-weight:800;line-height:1.25;letter-spacing:-0.02em;color:{INK};">{heading}</h1>
{body_html}
{cta}
{raw_link}
</td></tr>

<tr><td style="padding:22px 12px 0;text-align:center;">
{footer}
<p style="margin:0;font-family:{_FONT};font-size:12px;line-height:1.55;color:{_MUTED_ON_PAPER};">
Qonvo, your AI customer rep on WhatsApp, answering 24/7.
</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# --------------------------------------------------------------------------- #
# The four transactional emails -> (subject, text, html)
# --------------------------------------------------------------------------- #
#: What the rep actually does. Shown on the welcome email, because "AI WhatsApp
#: rep" tells a new owner almost nothing about what they just signed up for.
_CAPABILITIES: list[tuple[str, str]] = [
    ("Answers day and night", "in whatever language the customer writes in."),
    ("Knows your business", "prices, hours and policies, from documents you upload."),
    ("Understands voice notes", "and can reply with them too."),
    ("Books and captures", "appointments, orders and leads, straight into your calendar or sheet."),
    ("Knows when to stop", "and hands the conversation to you the moment it should."),
]

_SETUP_STEPS = [
    "Connect your WhatsApp number by scanning a QR code.",
    "Upload what your rep should know: a price list, an FAQ, your policies.",
    "Message the number yourself and watch it answer.",
]


def _quotas() -> tuple[int, str]:
    """The trial allowance, and the paid ones as a readable list.

    Read from the plan catalogue rather than typed here. plans.py exists so a
    quota lives in exactly one place; an email quietly promising 1,000 messages
    after someone edits Starter would be the catalogue failing at its one job.
    """
    trial = int(PLANS[TRIAL_PLAN].entitlements["monthly_message_quota"])
    paid = [
        int(p.entitlements["monthly_message_quota"])
        for key, p in PLANS.items()
        if key != TRIAL_PLAN
    ]
    formatted = [f"{q:,}" for q in sorted(paid)]
    if len(formatted) > 1:
        readable = ", ".join(formatted[:-1]) + " or " + formatted[-1]
    else:
        readable = formatted[0] if formatted else ""
    return trial, readable


def welcome(name: str | None, business: str, dashboard_url: str) -> tuple[str, str, str]:
    hello = f"Hi {name}," if name else "Hi there,"
    subject = f"Your AI rep for {business} is ready to set up"
    trial_quota, paid_quotas = _quotas()

    text = (
        f"{hello}\n\n"
        f"Welcome to Qonvo. Your AI WhatsApp rep for {business} is ready to set up.\n\n"
        "What it does once it is live:\n"
        + "".join(f"  - {t} {r}\n" for t, r in _CAPABILITIES)
        + "\nThree steps to go live:\n"
        + "".join(f"  {i}. {s}\n" for i, s in enumerate(_SETUP_STEPS, start=1))
        + f"\nOpen your dashboard: {dashboard_url}\n\n"
        f"You are on a {TRIAL_DAYS}-day free trial with {trial_quota:,} messages included. "
        f"When you are ready for more, the paid plans lift that to {paid_quotas} "
        f"messages a month: {dashboard_url}/billing\n\n"
        "Reply to this email if you want a hand getting set up. A person reads it.\n\n"
        "The Qonvo team"
    )

    body = (
        _p(hello)
        + _p(
            f"Your AI WhatsApp rep for <strong style=\"color:{INK};\">{business}</strong> is "
            "ready to set up. Here is what it will do for you."
        )
        + _feature_rows(_CAPABILITIES)
        + _divider()
        + _p("Three steps to go live", size=16, color=INK, top=20)
        + _numbered_steps(_SETUP_STEPS)
        + _volt_note(
            f"{TRIAL_DAYS} days free",
            f"Your trial includes {trial_quota:,} messages a month, which is plenty to see it "
            f"working on real customers. Paid plans lift that to {paid_quotas} when "
            f'you are ready: <a href="{dashboard_url}/billing" target="_blank" '
            f'style="color:{DEEP_FOREST};font-weight:700;">see the plans</a>.',
        )
    )
    html = shell(
        preheader=f"Three steps to put your AI rep for {business} live on WhatsApp.",
        eyebrow="Welcome aboard",
        heading="Your rep is ready to set up",
        body_html=body,
        cta_label="Open your dashboard",
        cta_url=dashboard_url,
        footer_note="Reply to this email if you want a hand getting set up. A person reads it.",
    )
    return subject, text, html


def password_reset(name: str | None, reset_url: str) -> tuple[str, str, str]:
    hello = f"Hi {name}," if name else "Hi there,"
    subject = "Reset your Qonvo password"
    text = (
        f"{hello}\n\n"
        "We received a request to reset your Qonvo password. Open the link below "
        "to choose a new one. It expires in 30 minutes:\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can safely ignore this email. Your "
        "password will not change.\n\n"
        "The Qonvo team"
    )
    body = _p(hello) + _p(
        "We got a request to reset your Qonvo password. Choose a new one with the "
        "button below. The link expires in 30 minutes."
    )
    html = shell(
        preheader="Reset your Qonvo password. The link expires in 30 minutes.",
        eyebrow="Account security",
        heading="Reset your password",
        body_html=body,
        cta_label="Choose a new password",
        cta_url=reset_url,
        footer_note="Did not request this? Ignore this email and your password will not change.",
    )
    return subject, text, html


def team_invite(business: str, role: str, accept_url: str) -> tuple[str, str, str]:
    subject = f"You are invited to {business} on Qonvo"
    text = (
        "Hi there,\n\n"
        f"You have been invited to join {business} on Qonvo as {role}.\n\n"
        "Qonvo is the AI rep that answers the business's customers on WhatsApp, "
        "day and night, and hands the conversation over to a person when it should.\n\n"
        "Accept your invitation and set up your account here. It expires in 7 days:\n\n"
        f"{accept_url}\n\n"
        "If you were not expecting this, you can ignore this email.\n\n"
        "The Qonvo team"
    )
    body = (
        _p(
            f'You have been invited to join <strong style="color:{INK};">{business}</strong> '
            f'on Qonvo as <strong style="color:{INK};">{role}</strong>.'
        )
        + _p(
            "Qonvo is the AI rep that answers the business's customers on WhatsApp, day and "
            "night, and hands the conversation to a person the moment it should."
        )
        + _p("Accept below to set up your account.")
    )
    html = shell(
        preheader=f"Join {business} on Qonvo as {role}.",
        eyebrow="Team invitation",
        heading=f"Join {business} on Qonvo",
        body_html=body,
        cta_label="Accept invitation",
        cta_url=accept_url,
        footer_note="This invite expires in 7 days. Not expecting it? You can ignore this email.",
    )
    return subject, text, html


def owner_alert(subject: str, body_text: str) -> str:
    """Branded HTML for owner alerts, e.g. a human handoff.

    The plain-text part is passed through unchanged by the caller; this only
    builds the HTML alternative. No CTA: the useful action is opening WhatsApp
    or the inbox, and which one depends on the alert.
    """
    paragraphs = "".join(_p(line) for line in body_text.split("\n\n") if line.strip())
    return shell(
        preheader=subject,
        eyebrow="Needs your attention",
        heading=subject,
        body_html=paragraphs or _p(body_text),
        footer_note="You are getting this because you are the owner of this Qonvo workspace.",
    )
