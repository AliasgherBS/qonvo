# Email setup

How to get `@qonvo.org` email working end to end: receiving, replying, sending
from the app, and using the address to register for services like a merchant of
record.

Costs and the comparison of providers are in
[`DEPLOYMENT-AND-COSTS.md` §5.1](DEPLOYMENT-AND-COSTS.md). This document is the
how.

---

## 1. What you are building

Three separate paths, often confused for one thing.

```
                        ┌──────────────────────────────┐
  customer replies ───► │  Cloudflare Email Routing    │ ──► your Gmail inbox
  Polar invoices        │  (receive, free, no mailbox) │
  service signups       └──────────────────────────────┘

  you reply       ───►  Gmail "Send mail as"  ──► Brevo SMTP ──► recipient
                        (envelope says support@qonvo.org)

  Qonvo sends     ───►  Brevo / Resend API    ──► recipient
  resets, alerts        (from noreply@send.qonvo.org)
```

Receiving costs nothing and needs no mailbox. Sending from the app must not go
through a personal Gmail, because Gmail's limits and reputation are not built for
it and the mail will start landing in spam.

**Prerequisite: already satisfied.** `qonvo.org` is live and its DNS is on
Cloudflare, since the site is served through a Cloudflare Tunnel. Nothing here
touches the tunnel or the existing A/CNAME records: email uses MX and TXT, which
are separate.

[`GOING-LIVE-ON-A-DOMAIN.md` §6](GOING-LIVE-ON-A-DOMAIN.md) is the short version
of this inside the go-live runbook. This document is the long version, and the
two agree.

---

## 2. Decide the addresses before touching DNS

| Address | Kind | Where it lives | Purpose |
|---|---|---|---|
| `hello@qonvo.org` | alias | forwards to your Gmail | General, the one on the website |
| `support@qonvo.org` | alias | forwards to your Gmail | Customer support |
| `billing@qonvo.org` | alias | forwards to your Gmail | **MoR, invoices, service signups** |
| `admin@qonvo.org` | alias | forwards to your Gmail | Domain, hosting, DNS registrations |
| `noreply@send.qonvo.org` | send only | Brevo/Resend, **no mailbox** | App mail: resets, welcome, alerts |

All four aliases land in one inbox. Nothing here needs a paid mailbox.

Use **`billing@`** for every paid service and for Polar. Not your personal Gmail:
the account then survives you changing personal address, and the paperwork lands
somewhere you can find during a KYC review.

---

## 3. Receiving: Cloudflare Email Routing

Free, 200 addresses and 200 destinations per domain, no message limit.

1. Cloudflare dashboard → your domain → **Email** → **Email Routing** → **Get started**.
2. Cloudflare offers to add the MX and SPF records automatically. **Accept.**
   It adds three MX records (`route1/2/3.mx.cloudflare.net`) and an SPF TXT.
3. **Destination addresses** → add your personal Gmail → confirm the mail
   Cloudflare sends to it. Nothing forwards until that link is clicked.
4. **Routing rules** → create one per alias from the table above, all pointing at
   the verified Gmail.
5. Optional: enable **catch-all** so a typo'd address still reaches you rather
   than bouncing.

Test by mailing `hello@qonvo.org` from any outside account. It should land in
Gmail within seconds.

> **MX records point at exactly one provider.** Turning on Email Routing takes
> over the domain's MX. If you later move to Zoho, you replace these records, you
> do not add to them. See §7.

---

## 4. Replying as `@qonvo.org` from Gmail

Cloudflare only receives. Replies need an SMTP relay, which the free Brevo
account in §5 provides.

1. Gmail → **Settings** → **Accounts and Import** → **Send mail as** → **Add
   another email address**.
2. Name: `Qonvo Support`. Address: `support@qonvo.org`. **Untick "Treat as an
   alias"** if you want replies to thread back to the role address.
3. SMTP server: `smtp-relay.brevo.com`, port `587`, your Brevo login and SMTP
   key, TLS on.
4. Gmail sends a confirmation code to `support@qonvo.org`, which Cloudflare
   forwards straight back to the same Gmail. Paste it in.

Now Gmail's compose window has a **From** dropdown, and replies to forwarded mail
go out as `support@qonvo.org`.

---

## 5. Sending from the app: Brevo or Resend

Brevo, because the free tier is **300/day (~9,000/month)** against Resend's
3,000/month **capped at 100/day**, and because the same account gives you the
SMTP relay §4 needs. Resend is the nicer API if you would rather pay $20 later.

### 5.1 Add the sending subdomain

Send app mail from **`send.qonvo.org`**, not the root domain. Separate subdomains
carry separate sender reputations, so a marketing mistake later cannot stop
password resets arriving.

1. Brevo → **Senders, Domains & Dedicated IPs** → **Domains** → **Add a domain**
   → `send.qonvo.org`.
2. Brevo shows a DKIM record, an SPF record and a DMARC record. Add each in
   Cloudflare DNS **on the `send` subdomain**, not the root.
3. Click **Authenticate**. Propagation is usually minutes.

Do **not** put the app's SPF on the root domain. The root's SPF belongs to
Cloudflare Email Routing from §3, and overwriting it silently breaks forwarding.

### 5.2 Point Qonvo at it

Config lives in `backend/app/core/config.py` and is read from the environment.
Either transport works; SMTP needs no extra code path.

```bash
# SMTP, via Brevo
QONVO_EMAIL_PROVIDER=smtp
QONVO_EMAIL_FROM="Qonvo <noreply@send.qonvo.org>"
QONVO_EMAIL_SMTP_HOST=smtp-relay.brevo.com
QONVO_EMAIL_SMTP_PORT=587
QONVO_EMAIL_SMTP_USER=<brevo login>
QONVO_EMAIL_SMTP_PASSWORD=<brevo smtp key>
QONVO_EMAIL_SMTP_STARTTLS=true
```

```bash
# or the Resend HTTP API
QONVO_EMAIL_PROVIDER=resend
QONVO_EMAIL_FROM="Qonvo <noreply@send.qonvo.org>"
QONVO_EMAIL_RESEND_API_KEY=<key>
```

`QONVO_EMAIL_PROVIDER=log` is the default and only writes to the log, which is
how the wiring is verified in dev without credentials. **Staging forces `log`**
so it can never mail a real customer; leave that alone.

Then **recreate**, do not restart:

```bash
docker compose up -d --force-recreate api worker scheduler
```

Env files are read at container **create**, so `docker compose restart` keeps the
old values and you will debug a change that never loaded. Then trigger a password
reset and confirm it arrives.

---

## 6. SPF, DKIM and DMARC

Three records, three jobs. Without all three, mail from a new domain goes to
spam.

| Record | Answers | Where |
|---|---|---|
| **SPF** | Which servers may send as this domain | TXT on each sending domain |
| **DKIM** | Was this signed by the domain's key | TXT the provider gives you |
| **DMARC** | What to do when SPF or DKIM fails | TXT on `_dmarc` |

Start DMARC permissive and tighten once you can see reports:

```
_dmarc.qonvo.org        TXT   v=DMARC1; p=none; rua=mailto:admin@qonvo.org
_dmarc.send.qonvo.org   TXT   v=DMARC1; p=none; rua=mailto:admin@qonvo.org
```

Move to `p=quarantine` after a couple of weeks of clean reports, then `p=reject`.
Going straight to `p=reject` on day one will bounce your own mail while the
records are still wrong.

Check the result at [mail-tester.com](https://www.mail-tester.com) — send it a
real app email and aim for 9/10 or better before launch.

---

## 7. When to upgrade to a real mailbox

Stay on forwarding until one of these is true:

- A service **refuses a forward-only address**, which some do for account
  recovery. This is the most likely trigger.
- You want mail out of your personal inbox, or a colleague needs access.
- You want IMAP on a phone or desktop client.

Then **Zoho Mail Lite, $1/user/month billed yearly**. Zoho's free tier still
exists for up to 5 users but is **web-only with no IMAP/POP**, and is no longer
offered to new signups in every region — do not plan around it.

Migrating from Cloudflare Routing to Zoho:

1. Zoho → add `qonvo.org` → verify by the TXT record it gives you.
2. Create **one** user, `you@qonvo.org`. Add `support@`, `billing@`, `hello@`,
   `admin@` as **aliases on that one user**, not as extra paid users.
3. In Cloudflare DNS, **delete the three Email Routing MX records and replace
   them** with Zoho's MX (`mx.zoho.com`, `mx2.zoho.com`, `mx3.zoho.com`).
4. Disable Cloudflare Email Routing so it stops claiming the domain.
5. Update the root SPF to Zoho's include. **Leave `send.qonvo.org` alone** — the
   app's sending records are on the subdomain and are unaffected.

The app's transactional sending does not change. That is the reason for the
subdomain split: you can swap mailbox providers without touching what Qonvo
sends.

---

## 8. Using the address for signups and the merchant of record

A forwarded address is a real address. It receives verification mails, invoices
and password resets, so it works for registering a VPS, a domain, an AI provider,
or **Polar**.

For Polar specifically:

- Register with **`billing@qonvo.org`**.
- Polar is the merchant of record and issues payouts through **Stripe Connect
  Express**. **Pakistan is on its supported payout list**, which settles an open
  question in the costs doc. Confirm the receiving method during onboarding.
- Business verification takes anywhere from ~24–72 hours to about two weeks
  depending on whose account you read. Budget for it, and do not schedule a
  launch behind it.
- Verification reviewers want to see the full customer journey: free user clicks
  upgrade, pays, gets access. Have a screen recording or a test discount code
  ready.
- Invoices and KYC correspondence will arrive at that address for years. Do not
  use an address you might lose.

If any service rejects the forwarded address, that is the moment to spend the $1
on Zoho, not before.

---

## 9. Checklist

- [ ] Domain DNS on Cloudflare
- [ ] Email Routing on, MX + SPF added, destination Gmail verified
- [ ] `hello@`, `support@`, `billing@`, `admin@` routing rules created
- [ ] Catch-all enabled
- [ ] Inbound test mail arrives in Gmail
- [ ] Gmail *Send mail as* configured for `support@`, confirmation code accepted
- [ ] Outbound reply arrives showing `support@qonvo.org` as sender
- [ ] `send.qonvo.org` added and authenticated at the transactional provider
- [ ] DKIM, SPF, DMARC present on `send.qonvo.org`
- [ ] DMARC `p=none` on both root and subdomain, `rua` pointing somewhere you read
- [ ] `QONVO_EMAIL_*` set, containers **force-recreated** (not restarted)
- [ ] Password reset mail actually received
- [ ] mail-tester.com scores 9/10 or better
- [ ] `billing@qonvo.org` used for Polar and every paid service

---

## 10. Things that will bite

- **Two MX providers at once.** MX points to one place. Enabling Zoho without
  removing Cloudflare Routing silently loses mail.
- **Overwriting the root SPF.** Cloudflare Routing owns the root SPF. Adding the
  app's SPF there breaks forwarding. The app's records go on `send.`.
- **Two SPF TXT records on one name.** Illegal, and it fails closed. Merge into
  one `v=spf1 ... ~all`.
- **Sending app mail from the root domain.** Works, until a marketing send burns
  the reputation and password resets stop arriving. Use the subdomain from day one.
- **Resend's daily cap.** 3,000/month reads generous; the **100/day** is what
  actually binds.
- **`p=reject` too early.** Bounces your own mail while records settle.
- **Restarting instead of recreating** after an email env change. The old values
  survive. `--force-recreate`, every time.
- **Changing the domain** invalidates everything here plus the app's own
  hostname wiring, and the two Google redirect URIs now live on **different
  hosts**. Do not work it out from memory:
  [`GOING-LIVE-ON-A-DOMAIN.md`](GOING-LIVE-ON-A-DOMAIN.md) is the runbook.

---

_Checked 2026-09-06: Cloudflare Email Routing free limits; Zoho Mail free and
Mail Lite plans; Migadu and Purelymail pricing; Resend, Brevo, Amazon SES,
Mailgun free tiers and paid rates; Google Workspace and Microsoft 365 seat
prices; Polar supported payout countries and merchant onboarding; email
subdomain and no-reply deliverability practice._
