"""Branded HTML email templates (transactional).

Every email ships as **multipart/alternative**: a plain-text part (deliverability
+ clients that block HTML) and this branded HTML part. The Qonvo logo is rendered
in HTML/CSS (a green "Q" badge + wordmark) rather than a hosted image on purpose —
most email clients block remote images by default, so a CSS mark always renders.

Table-based layout + fully inline styles = the only thing that survives Gmail,
Outlook, and Apple Mail intact.
"""

from __future__ import annotations

# --- Brand tokens (mirrors dashboard/app/globals.css) ---
_GREEN = "#00d26a"
_GREEN_STRONG = "#018548"
_INK = "#0b1f17"
_BODY = "#38463f"
_MUTED = "#5b6b62"
_PAPER = "#f1f7f4"
_CARD_BORDER = "#e5ede8"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:26px 0 6px;"><tr>'
        f'<td style="background:{_GREEN};border-radius:10px;">'
        f'<a href="{url}" target="_blank" '
        f"style=\"display:inline-block;padding:14px 30px;font-family:{_FONT};"
        f'font-weight:700;font-size:15px;color:#ffffff;text-decoration:none;">{label}</a>'
        "</td></tr></table>"
    )


def shell(
    *,
    preheader: str,
    heading: str,
    body_html: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
) -> str:
    """Wrap body content in the branded Qonvo shell."""
    cta = _button(cta_label, cta_url) if cta_label and cta_url else ""
    # Show the raw link under a button too (buttons can be stripped; links aren't).
    raw_link = (
        f'<p style="margin:14px 0 0;font-family:{_FONT};font-size:12px;line-height:1.5;'
        f'color:{_MUTED};">Or paste this link into your browser:<br>'
        f'<a href="{cta_url}" target="_blank" style="color:{_GREEN_STRONG};word-break:break-all;">{cta_url}</a></p>'
        if cta_url
        else ""
    )
    footer = (
        f'<p style="margin:0 0 6px;font-family:{_FONT};font-size:12px;line-height:1.5;color:{_MUTED};">{footer_note}</p>'
        if footer_note
        else ""
    )
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{heading}</title>
</head>
<body style="margin:0;padding:0;background:{_PAPER};-webkit-font-smoothing:antialiased;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_PAPER};">
<tr><td align="center" style="padding:32px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
<tr><td style="padding:4px 6px 22px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td style="background:{_GREEN};border-radius:10px;height:36px;width:36px;text-align:center;vertical-align:middle;font-family:{_FONT};font-weight:800;font-size:19px;color:#ffffff;">Q</td>
<td style="padding-left:10px;font-family:{_FONT};font-weight:800;font-size:20px;letter-spacing:-0.02em;color:{_INK};">qonvo</td>
</tr></table>
</td></tr>
<tr><td style="background:#ffffff;border:1px solid {_CARD_BORDER};border-radius:16px;padding:38px 38px 34px;">
<h1 style="margin:0 0 16px;font-family:{_FONT};font-size:22px;font-weight:800;line-height:1.3;color:{_INK};">{heading}</h1>
{body_html}
{cta}
{raw_link}
</td></tr>
<tr><td style="padding:22px 10px 8px;text-align:center;">
{footer}
<p style="margin:0;font-family:{_FONT};font-size:12px;line-height:1.5;color:{_MUTED};">
Qonvo — your AI customer rep on WhatsApp, answering 24/7.
</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _p(text: str) -> str:
    return f'<p style="margin:0 0 14px;font-family:{_FONT};font-size:15px;line-height:1.6;color:{_BODY};">{text}</p>'


# --------------------------------------------------------------------------- #
# The four transactional emails → (subject, text, html)
# --------------------------------------------------------------------------- #
def welcome(name: str | None, business: str, dashboard_url: str) -> tuple[str, str, str]:
    hello = f"Hi {name}," if name else "Hi there,"
    subject = "Welcome to Qonvo \U0001f44b"
    text = (
        f"{hello}\n\n"
        f"Welcome to Qonvo — your AI WhatsApp rep for {business} is ready to set up.\n\n"
        "Next steps:\n"
        "  1. Connect your WhatsApp number (scan the QR).\n"
        "  2. Add what your rep should know (hours, prices, policies).\n"
        "  3. Message the number to see it reply.\n\n"
        f"Open your dashboard: {dashboard_url}\n\n"
        "You're on a 14-day free trial. Reply to this email if you need a hand.\n\n"
        "— The Qonvo team"
    )
    steps = "".join(
        f'<tr><td style="padding:6px 0;font-family:{_FONT};font-size:15px;line-height:1.5;color:{_BODY};">'
        f'<span style="display:inline-block;width:22px;height:22px;background:{_PAPER};border-radius:11px;'
        f'text-align:center;font-weight:700;color:{_GREEN_STRONG};font-size:13px;margin-right:10px;">{i}</span>{s}</td></tr>'
        for i, s in enumerate(
            [
                "Connect your WhatsApp number (scan the QR).",
                "Add what your rep should know — hours, prices, policies.",
                "Message the number and watch it reply.",
            ],
            start=1,
        )
    )
    body = (
        _p(f"{hello}")
        + _p(f"Your AI WhatsApp rep for <strong>{business}</strong> is ready to set up. Three quick steps to go live:")
        + f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 8px;">{steps}</table>'
    )
    html = shell(
        preheader=f"Your AI WhatsApp rep for {business} is ready to set up.",
        heading="Welcome to Qonvo",
        body_html=body,
        cta_label="Open your dashboard",
        cta_url=dashboard_url,
        footer_note="You're on a 14-day free trial. Just reply to this email if you need a hand.",
    )
    return subject, text, html


def password_reset(name: str | None, reset_url: str) -> tuple[str, str, str]:
    hello = f"Hi {name}," if name else "Hi there,"
    subject = "Reset your Qonvo password"
    text = (
        f"{hello}\n\n"
        "We received a request to reset your Qonvo password. Click the link below "
        "to choose a new one — it expires in 30 minutes:\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email; your "
        "password won't change.\n\n"
        "— The Qonvo team"
    )
    body = _p(f"{hello}") + _p(
        "We got a request to reset your Qonvo password. Choose a new one with the "
        "button below — the link expires in 30 minutes."
    )
    html = shell(
        preheader="Reset your Qonvo password (link expires in 30 minutes).",
        heading="Reset your password",
        body_html=body,
        cta_label="Choose a new password",
        cta_url=reset_url,
        footer_note="Didn't request this? You can ignore this email — your password won't change.",
    )
    return subject, text, html


def team_invite(business: str, role: str, accept_url: str) -> tuple[str, str, str]:
    subject = f"You're invited to {business} on Qonvo"
    text = (
        "Hi there,\n\n"
        f"You've been invited to join {business} on Qonvo as {role}. "
        "Qonvo is the AI WhatsApp rep that answers customers for the business.\n\n"
        "Accept your invitation and set up your account here (expires in 7 days):\n\n"
        f"{accept_url}\n\n"
        "If you weren't expecting this, you can ignore this email.\n\n"
        "— The Qonvo team"
    )
    body = _p(
        f"You've been invited to join <strong>{business}</strong> on Qonvo as "
        f'<strong>{role}</strong>.'
    ) + _p("Qonvo is the AI WhatsApp rep that answers the business's customers 24/7. Accept below to set up your account.")
    html = shell(
        preheader=f"Join {business} on Qonvo as {role}.",
        heading=f"Join {business} on Qonvo",
        body_html=body,
        cta_label="Accept invitation",
        cta_url=accept_url,
        footer_note="This invite expires in 7 days. Weren't expecting it? You can ignore this email.",
    )
    return subject, text, html


def owner_alert(subject: str, body_text: str) -> str:
    """Branded HTML for owner alerts (e.g. human handoff). Plain text is passed
    through unchanged by the caller; this only builds the HTML alternative."""
    paragraphs = "".join(_p(line) for line in body_text.split("\n\n") if line.strip())
    return shell(
        preheader=subject,
        heading=subject,
        body_html=paragraphs or _p(body_text),
        footer_note="You're getting this because you're the owner of this Qonvo workspace.",
    )


__all__ = ["owner_alert", "password_reset", "shell", "team_invite", "welcome"]
