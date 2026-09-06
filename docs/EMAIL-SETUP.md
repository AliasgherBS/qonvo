# Email setup

How to get `@qonvo.org` email working end to end: receiving, replying, sending
from the app, and using the address to register for services like a merchant of
record.

Costs and the provider comparison are in
[`DEPLOYMENT-AND-COSTS.md` §5.1](DEPLOYMENT-AND-COSTS.md). This document is the
how. [`GOING-LIVE-ON-A-DOMAIN.md` §6](GOING-LIVE-ON-A-DOMAIN.md) is the two
paragraph version inside the go-live runbook; the three agree.

**Total cost: about $1/month.**

---

## 1. The shape of it

Two jobs, two products, one vendor.

```
  customer replies   ───►  Zoho Mail  ───►  your inbox
  Polar invoices           (MX on qonvo.org)
  service signups
  you reply          ◄───

  Qonvo sends        ───►  ZeptoMail  ───►  recipient
  welcome, reset,          (send.qonvo.org, no mailbox)
  invite, owner alert
```

| Job | Product | Cost |
|---|---|---:|
| Mailbox, aliases, receiving, replying | **Zoho Mail Lite**, 1 user | **$1/mo** billed yearly |
| The four emails the app sends | **ZeptoMail** | 10,000 free, then **$2.50/10,000** |
| DNS | Cloudflare | $0 |

**Why two products and not one.** Zoho Mail's own SMTP is a human mailbox with a
daily cap, and using it for app mail would put your password resets on the same
sender reputation as your support inbox. ZeptoMail is a separate reputation built
for machine mail, and it **refuses promotional email by design** — the split this
document recommends, enforced by the vendor rather than by your discipline.

**Why not Brevo.** Its free tier is 300/day forever against ZeptoMail's one-off
10,000, which looks more generous until you notice it **stamps the Brevo logo on
every email you send**. Removing it costs the Starter plan plus an add-on, about
$20/month. ZeptoMail at Qonvo's volume is roughly $2.50 every six months.

**Why not Cloudflare Email Routing.** Nothing is wrong with it, and it is the
right answer if you refuse to spend $1: free, 200 addresses, no message limit.
But it only *forwards*. No mailbox, no storage, and it cannot send, so replying
as `support@` needs a separate relay bolted on. It is also either/or, never both:
**MX points at exactly one provider.** Once you buy Zoho, Cloudflare does your
DNS and nothing else.

**Prerequisite: already satisfied.** `qonvo.org` is live with DNS on Cloudflare,
since the site is served through a Cloudflare Tunnel. Nothing here touches the
tunnel or the existing CNAME records: email is MX and TXT, which are separate.

### Who does what

Vendor signup and payment are manual. Everything downstream of them is not.

| Step | Who | How |
|---|---|---|
| Buy Zoho Mail Lite, sign up for ZeptoMail | **you** | card details, no API exists before an account does |
| Create a Cloudflare API token | **you** | dashboard, 2 minutes, [§3.0](#30-the-cloudflare-token) |
| Every DNS record | scripted | [`scripts/dns-email.sh`](../scripts/dns-email.sh) |
| Zoho user + the four aliases | you, or API | 5 clicks, or the admin REST API if you want it reproducible |
| ZeptoMail agent, domain, send token | you, or API | `POST /v1.1/domains`, `POST /v1.1/agents/{key}/apikeys` |
| App wiring, recreate, tests | scripted | §4.2 |

**The values that cannot be automated are the DKIM keys and the domain
verification tokens.** They are generated per account, so no amount of tooling
derives them: each vendor shows you a string and you hand it over. That is the
one genuine serialisation point in this document.

**There is no Zoho CLI.** Zoho's MCP server is for *mailbox* actions -- reading,
sending, searching your inbox -- not admin provisioning, so it does not help
with any of the setup here. Cloudflare does publish official MCP servers, but a
scoped API token with `curl` is simpler for a handful of records and leaves a
script behind rather than a conversation.

### 3.0 The Cloudflare token

`~/.cloudflared/cert.pem` is **not** enough. It holds only an Argo Tunnel token,
and `cloudflared tunnel route dns` creates CNAMEs pointing at a tunnel -- it
cannot write MX or TXT at all.

Cloudflare dashboard -> **My Profile -> API Tokens -> Create Token -> "Edit zone
DNS"**, scoped to `qonvo.org`. That template is `Zone:DNS:Edit`; add
`Zone:Zone:Read` so the script can resolve the zone id.

```bash
export CLOUDFLARE_API_TOKEN=...
./scripts/dns-email.sh check      # what exists, and what contradicts what
```

`check` reads only. It also refuses to be quiet about the two failures this
document warns about: a second SPF record on one name, and MX pointing at more
than one provider. The script writes **MX and TXT only** -- the tunnel CNAMEs
that make the site reachable are outside what it can touch, by construction.

---

## 2. Decide the addresses first

| Address | What it is | Cost |
|---|---|---:|
| **`ali@qonvo.org`** | **the one real user.** Your login and the admin account | $1/mo |
| `hello@qonvo.org` | alias → same inbox. The one on the website | free |
| `support@qonvo.org` | alias → same inbox. Customer support | free |
| `billing@qonvo.org` | alias → same inbox. **MoR, invoices, paid services** | free |
| `admin@qonvo.org` | alias → same inbox. Domain, hosting, DNS accounts | free |
| `noreply@send.qonvo.org` | **not a mailbox.** ZeptoMail only | free |

Aliases are unlimited on Zoho and all land in the same inbox. You read them in
one place and reply *as* whichever you choose.

**Do not buy a second seat for `support@` or `billing@`.** That is the mistake
this layout exists to avoid, and it is what turns a $1 bill into a $5 one.

**Make the paid user a person, not a role.** `ali@qonvo.org` is your login and
admin identity; role addresses are aliases you can hand to someone later without
giving away the account. Making `hello@` the user works today and costs you a
migration the first time you add a colleague.

**Use `billing@` for every paid service and for Polar**, never a personal Gmail.
It survives you changing personal address, and MoR invoices and KYC
correspondence land somewhere findable for years.

---

## 3. Zoho Mail: the mailbox

1. Sign up at Zoho Mail, choose **Mail Lite**, 1 user, billed yearly.
2. Add `qonvo.org` and verify it with the TXT record Zoho gives you.
3. Create the single user `ali@qonvo.org`.
4. Add `hello@`, `support@`, `billing@`, `admin@` as **aliases on that user**,
   not as new users. Zoho: *Users → the user → Mail Accounts → Email Aliases*.
5. Add Zoho's **three MX records** to Cloudflare DNS on the root.
   `./scripts/dns-email.sh zoho-mx` writes exactly these:

   | Type | Name | Value | Priority |
   |---|---|---|---:|
   | MX | `@` | `mx.zoho.com` | 10 |
   | MX | `@` | `mx2.zoho.com` | 20 |
   | MX | `@` | `mx3.zoho.com` | 50 |

   Cloudflare never proxies MX, so there is no grey cloud to set.
6. Add Zoho's SPF and DKIM on the root (§5):

   ```bash
   ./scripts/dns-email.sh spf  root "v=spf1 include:zoho.com ~all"
   ./scripts/dns-email.sh dkim zmail._domainkey "<the value Zoho shows you>"
   ./scripts/dns-email.sh txt  zoho-verification "<the token Zoho shows you>"
   ```

Test by mailing `hello@qonvo.org` from an outside account.

> If Cloudflare Email Routing was ever enabled on this domain, **turn it off
> first**. Two providers cannot both hold the MX.

---

## 4. ZeptoMail: what the app sends

Qonvo sends exactly four transactional emails today, all machine to human:

| Trigger | Template |
|---|---|
| Signup, and Google SSO signup | `welcome` |
| Forgot password | `password_reset` |
| Inviting a teammate | `team_invite` |
| `human_handoff` escalation | `owner_alert` |

### 4.1 Set up the sending subdomain

Send them from **`send.qonvo.org`**, never the root. Separate subdomains carry
separate sender reputations, so a marketing mistake later cannot stop a password
reset arriving. Doing this on day one is free; retrofitting it after a
reputation hit is not.

1. ZeptoMail → **Mail Agents** → create one, e.g. `qonvo-app`.
2. **Domains** → add `send.qonvo.org`.
3. Add the DKIM and SPF records it gives you in Cloudflare, **on the `send`
   subdomain**, not the root.
4. Verify, then generate a **Send Mail token**.

Do **not** put ZeptoMail's SPF on the root. The root's SPF belongs to Zoho, and
overwriting it breaks your mailbox.

### 4.2 Point Qonvo at it

ZeptoMail speaks plain SMTP, so the existing `smtp` transport covers it with no
code change.

```bash
QONVO_EMAIL_PROVIDER=smtp
QONVO_EMAIL_FROM="Qonvo <noreply@send.qonvo.org>"
QONVO_EMAIL_REPLY_TO=support@qonvo.org
QONVO_EMAIL_SMTP_HOST=smtp.zeptomail.com
QONVO_EMAIL_SMTP_PORT=587
QONVO_EMAIL_SMTP_USER=emailapikey
QONVO_EMAIL_SMTP_PASSWORD=<the Send Mail token>
QONVO_EMAIL_SMTP_STARTTLS=true
```

The username is the literal string `emailapikey`; the token goes in the password
field. Check the host against ZeptoMail's own setup screen, which shows the
region-correct value.

`QONVO_EMAIL_PROVIDER=log` is the default and only writes to the log, which is
how wiring is verified in dev without credentials. **Staging forces `log`** so it
can never mail a real customer. Leave that alone.

Then **recreate, do not restart**:

```bash
docker compose up -d --force-recreate api worker scheduler
```

Env files are read at container **create**, so `docker compose restart` keeps the
old values and you will spend an hour debugging a change that never loaded.
Then trigger a password reset and confirm it arrives.

### 4.3 Replies

`QONVO_EMAIL_REPLY_TO` above is doing real work. Everything Qonvo sends comes
from `noreply@send.qonvo.org`, which has **no mailbox behind it** -- that is the
point of a sending subdomain. Without a Reply-To, an owner who hits reply on an
escalation is answering nothing: the mail leaves their client, and no one ever
receives it.

It applies to all four emails, not just `owner_alert`. A new owner replying to
their welcome email with a question is lost exactly as thoroughly.

Set it to `support@qonvo.org` -- an alias on the one Zoho mailbox, so it costs
nothing and lands where you already read.

---

## 5. SPF, DKIM and DMARC

Three records, three jobs. Without all three, mail from a new domain goes to
spam.

| Record | Answers | Where |
|---|---|---|
| **SPF** | Which servers may send as this domain | TXT, one per sending domain |
| **DKIM** | Was this signed by the domain's key | TXT the provider gives you |
| **DMARC** | What to do when SPF or DKIM fails | TXT on `_dmarc` |

Two sending domains means two sets:

| Name | Purpose | Provider |
|---|---|---|
| `qonvo.org` | Mail you type | Zoho |
| `send.qonvo.org` | Mail the app sends | ZeptoMail |

Start DMARC permissive on both. `./scripts/dns-email.sh dmarc` writes exactly
these two:

```
_dmarc.qonvo.org        TXT   v=DMARC1; p=none; rua=mailto:admin@qonvo.org
_dmarc.send.qonvo.org   TXT   v=DMARC1; p=none; rua=mailto:admin@qonvo.org
```

ZeptoMail's own records go on the `send` name, never the root:

```bash
./scripts/dns-email.sh spf  send "v=spf1 include:zeptomail.zoho.com ~all"
./scripts/dns-email.sh dkim zmail._domainkey.send "<the value ZeptoMail shows you>"
```

Move to `p=quarantine` after a couple of weeks of clean reports, then `p=reject`.
Going straight to `p=reject` bounces your own mail while the records are still
wrong.

Verify at [mail-tester.com](https://www.mail-tester.com) — send it a real app
email and aim for 9/10 or better before launch.

---

## 6. Using the address for signups and the merchant of record

A real Zoho mailbox is accepted everywhere, including services that reject
forward-only addresses. For Polar:

- Register with **`billing@qonvo.org`**.
- Polar is the merchant of record and pays out through **Stripe Connect
  Express**. **Pakistan is on its supported list**, which settles an open
  question in the costs doc.
- Business verification runs anywhere from ~24–72 hours to about two weeks
  depending on whose account you read. Do not schedule a launch behind it.
- Reviewers want to see the full customer journey: free user clicks upgrade,
  pays, gets access. Have a screen recording or a test discount code ready.

---

## 7. Checklist

- [ ] Cloudflare API token created, `./scripts/dns-email.sh check` runs clean
- [ ] Cloudflare Email Routing **off**, if it was ever on
- [ ] Zoho Mail Lite bought, 1 user `ali@qonvo.org`
- [ ] `hello@`, `support@`, `billing@`, `admin@` added as **aliases**, not users
- [ ] Zoho MX records on the root, **DNS only** (grey cloud)
- [ ] Zoho SPF + DKIM on the root
- [ ] Inbound test mail arrives
- [ ] Reply sent as `support@` and received correctly
- [ ] ZeptoMail Mail Agent created, `send.qonvo.org` added and verified
- [ ] ZeptoMail SPF + DKIM on the **`send`** subdomain
- [ ] DMARC `p=none` on both names, `rua` pointing somewhere you read
- [ ] `QONVO_EMAIL_*` set, including `QONVO_EMAIL_REPLY_TO`, containers **force-recreated**
- [ ] Password reset actually received
- [ ] Reply to a Qonvo email lands in the Zoho inbox
- [ ] mail-tester.com 9/10 or better
- [ ] `billing@qonvo.org` used for Polar and every paid service

---

## 8. Things that will bite

- **Two MX providers at once.** MX points to one place. Leaving Cloudflare
  Routing enabled while adding Zoho silently loses mail.
- **Restarting instead of recreating** after an email env change. The old values
  survive. `--force-recreate`, every time.
- **Overwriting the root SPF.** The root belongs to Zoho. ZeptoMail's records go
  on `send.`.
- **Two SPF TXT records on one name.** Illegal, and it fails closed. Merge into
  one `v=spf1 ... ~all`.
- **Proxying MX through Cloudflare.** Mail records must be grey cloud. Cloudflare
  proxies HTTP, not SMTP.
- **Sending app mail from the root domain.** Works, until something burns the
  reputation and password resets stop arriving.
- **`p=reject` too early.** Bounces your own mail while records settle.
- **Changing the domain** invalidates everything here plus the app's hostname
  wiring, and the two Google redirect URIs live on **different hosts**. Do not
  work it out from memory:
  [`GOING-LIVE-ON-A-DOMAIN.md`](GOING-LIVE-ON-A-DOMAIN.md) is the runbook.

---

## 9. If deliverability disappoints

The known weakness of ZeptoMail, from operators running it for years, is that
**some Zoho sending IPs get blacklisted and Zoho does not automatically retry
from a clean one.** Most report good delivery; a minority report exactly this.

If mail-tester scores poorly or real users stop receiving resets, the fallback
is **Amazon SES at $0.10 per 1,000** — cheaper than ZeptoMail and the best
regarded of the affordable options. The cost is setup: you start in a sandbox
that only mails verified addresses and must request production access.

Nothing about the mailbox changes if you switch. That is the point of putting
app mail on its own subdomain: the sender can be replaced without touching
`qonvo.org`.

---

_Checked 2026-09-06: Zoho Mail Lite and Zoho Mail free plan limits; ZeptoMail
pricing, free credit and transactional-only policy; Brevo free plan limits and
logo-removal add-on cost; Amazon SES rates and sandbox; Cloudflare Email Routing
free limits; Polar supported payout countries and merchant onboarding; operator
reports on ZeptoMail deliverability from LowEndTalk._
