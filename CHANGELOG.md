# Changelog

All notable changes to Qonvo. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Branch flow: work lands on a feature branch, merges to `dev`, and is released to `main`
with an annotated `vX.Y.Z` tag. `Unreleased` below is what sits on `dev` awaiting a
release. See [CONTRIBUTING.md](CONTRIBUTING.md).

## [Unreleased]

### Security

- **`script-src` no longer allows `'unsafe-inline'`.** A per-request nonce
  replaces it, so the policy allows our own inline scripts specifically rather
  than inline scripts generally: a browser runs a script only if it carries this
  response's value, and an injected one cannot know it. That moved the policy
  from `next.config.ts`, where `headers()` is evaluated once at build time, into
  middleware. Every redirect path is covered too, since a response that skipped
  the wrapper answered with no policy at all, and `/login` is the response an
  unauthenticated visitor sees most often.


## [0.10.1] - 2026-09-08

### Fixed

- **Cancelling a plan returned 422.** `apiFetch` already stringifies a plain
  object and sets `Content-Type`, and only for a plain object, so passing an
  already-stringified body skipped both and the API received JSON with no content
  type. The same mistake was in the rep on/off toggle, which had never been
  exercised. `apiFetch` now warns in development when handed a stringified body,
  since the failure surfaces two layers from its cause.

- **A customer with one payment could not get an invoice.** The link was only
  offered when the provider reported the document as generated, and that is false
  on every fresh order: Polar issues an invoice *number* at purchase and renders
  the PDF only when asked. Invoices are now generated on demand, and the link is
  fetched per click because the provider's URL is signed and short-lived.

- Cloudflare injects its Web Analytics beacon at the edge, so the CSP blocked a
  script this codebase does not add and cannot remove, producing a violation on
  every page load and a follow-on TypeError from the half-loaded script.

### Changed

- **Plan management no longer leaves the app.** Changing plan happens in place and
  is prorated by the provider; cancel-and-resubscribe would have restarted the
  billing period and charged full price on the day somebody downgraded. What
  remains in the provider's portal is card details and only that, since hosting a
  card form means handling card data. The button says "Update card" rather than
  "Manage plan", which had been sending people away to do things the billing page
  could already do.

- The Terms name **"Aliasghar Ezzy, trading as Qonvo"** rather than "Qonvo".
  Qonvo is a product name; with no company registered the seller is a natural
  person, and a Terms page naming an entity that does not exist against a payment
  provider's KYC naming an individual is the mismatch that fails a
  merchant-of-record review.


## [0.10.0] - 2026-09-08

The release that made Qonvo sellable: a public domain, real email, a payment
gateway that has taken a real payment, and limits on everything that costs money.

### Added

- **Live on `qonvo.org`**, served from a Cloudflare Tunnel so no public IP or port
  forwarding is needed. `qonvo-up.sh` now curls both public URLs at the end rather
  than reporting that a tunnel started: a tunnel that connects but routes nowhere
  looks identical to a healthy one from the machine it runs on. Runbook, including
  rollback: [docs/GOING-LIVE-ON-A-DOMAIN.md](docs/GOING-LIVE-ON-A-DOMAIN.md).

- **Email on the domain**, about $1/month: Zoho Mail for the mailbox, ZeptoMail for
  what the app sends, from `send.qonvo.org` so a marketing mistake can never stop a
  password reset arriving. `scripts/dns-email.sh` writes the records idempotently and
  its `check` subcommand detects the three ways this silently breaks. See
  [docs/EMAIL-SETUP.md](docs/EMAIL-SETUP.md).

- **Polar as merchant of record.** A full adapter behind the existing provider seam,
  covering checkout, both of Polar's webhook signing schemes (it changed them on
  2026-09-08), payment history, an authenticated portal link, and in-app cancel and
  resume at end of period. Verified end to end against a real sandbox payment.

- **Voice allowance**, 5/20/100 minutes by plan. Voice was ungated and is 54-74% of
  per-tenant AI cost, so an unlimited-voice tenant on the largest plan cost about $54
  a month against $30 of revenue. Running out **degrades to text** rather than going
  silent, and the customer is told once per period.

- **Input caps**, at the API boundary and again at ingestion, because a URL source has
  no size until it has been fetched. Prompt fields are small and fixed; knowledge is
  generous and per-plan, since retrieval means a large corpus never makes a reply more
  expensive.

- **Activation.** A new tenant's rep now starts **off**. Previously it began answering
  real customers from an empty knowledge base the moment the QR code was scanned.
  While off, messages still arrive and are visible; the owner answers by hand.

- **Usage visibility.** Meters for messages, voice, seats and knowledge on the owner's
  billing page, and a fleet view sorted worst-first in the admin console, both from
  one computation so the two can never disagree.

- **Onboarding**: a five-step checklist that ends in switching the rep on, so
  onboarding and going live are one journey, plus a four-step tour over the real UI.

- **Rate limiting** on login, signup and password reset. Two keys per attempt, and the
  account counter records failures only, so an attacker cannot lock a victim out of
  their own account by failing on their behalf.

- **Security headers on both hosts**, set in application middleware rather than the
  proxy so they survive the move from Cloudflare Tunnel to Caddy.

- [docs/DEPLOYMENT-AND-COSTS.md](docs/DEPLOYMENT-AND-COSTS.md): measured resource
  profile, per-tenant storage model, VPS provider comparison at September 2026 rates,
  and the self-hosted versus managed Postgres decision. AI costs are catalogued
  **provider-agnostically** — 18 language models, 11 TTS and 13 STT providers, each
  normalised to this deployment's measured cost per 1,000 replies — plus a section on
  what can actually be bought and paid for from Pakistan.

- [docs/SECURITY-AUDIT.md](docs/SECURITY-AUDIT.md): the findings, the fixes, and what
  is still open.

### Changed

- Transactional emails are on the **actual brand palette**. They had drifted to a
  near-miss set that nothing checked, because the brand gate only walks the dashboard
  tree. A new plan-confirmation email says what the provider's receipt cannot: not
  that a business paid $18, but that their allowance went from 300 messages to 5,000.

- The **engine picker is off the owner's Business page**. Choosing a model is not a
  decision a business owner is equipped to make, and every wrong answer costs quality
  or money with no signal. Still editable from the admin console for incident pinning.

- Trial terms live in one place and a test fails if the number is retyped anywhere
  else, across the Python/TypeScript boundary.

### Fixed

- **The upload route read whole files into memory.** `await file.read()` with no size
  check anywhere, so one large upload was an availability problem, not a cost one.

- **`knowledge_chars` measured the wrong table.** A tenant showed 2 sources and 0
  characters against 7,775 genuinely stored: `sources.content` is NULL for anything
  uploaded or fetched. The cap would not have bound at all on file-based knowledge.

- **A customer's first payment resolved to no tenant.** The tenant id was written into
  checkout metadata and never read back, and the event that creates the subscriptions
  row is the first one, so there was nothing to match on. They would have kept their
  old plan having paid for a new one, silently, with the provider seeing a 200.

- **An authentic webhook we do not act on answered 401.** Providers send far more
  event types than any integration uses, and a provider that keeps getting errors
  eventually disables the endpoint.

- **Ten live secrets were in git history.** `.env` was tracked once; a removed file
  stays in history. Four were also placeholder-shaped strings, which is worse: those
  are guessable with no repository access. All rotated by
  `scripts/rotate-secrets.sh`, including re-encrypting what the Fernet key protects.

- **A credential in the URL.** Polar appends a session token to its success URL, so it
  reached browser history, `Referer` and access logs. Stripped in middleware, with
  `/reset-password` and `/accept-invite` exempt because our own emails link there.

## [0.9.0] - 2026-09-05

The first tagged release. Everything before it was untagged work on `main`. This
marks the product as live-verified against a real WhatsApp number, with the
billing, staging, CI and test-harness work that closed the last gaps before it
could be sold.

### Added

- **Automated end-to-end smoke test** (`./scripts/e2e-smoke.sh`): 45 checks over
  infrastructure, auth, every owner read endpoint, the billing lifecycle, knowledge
  ingestion and the inbound pipeline, driven by signed synthetic webhooks so no phone
  is needed. Plus [docs/E2E-LIVE-TEST-PLAN.md](docs/E2E-LIVE-TEST-PLAN.md) for the
  manual half and a standing record of what has actually been exercised.

- **Billing subsystem**, provider-agnostic and shaped around a merchant of record,
  shipped with a manual (admin-recorded) adapter so it works before any gateway
  account exists. Plan catalogue in code with entitlements only, `subscriptions` and
  `billing_events` tables (migration `0008`), a pure `service_state` entitlement gate,
  seat limits on team invites, an idempotent `POST /webhooks/billing/{provider}` route,
  and `PUT /api/admin/tenants/{id}/subscription`. Prices deliberately live with the
  payment provider, never in this repository.
- **Staging environment** (`./qonvo-staging.sh`): a second compose project beside
  production with its own volumes, secrets and ports, and email forced to `log` so it
  can never reach a real customer.
- **New-number warm-up** is now actually applied: 50 sends/day for week one, 150 for
  week two, then normal, advanced by a daily scheduler job.
- `QONVO_WAHA_FULL_SYNC` (default off) — see Changed.
- Continuous integration: backend tests, lint, migrations and the dashboard build and
  brand gates run on every push and pull request.

### Changed

- **WAHA no longer backfills WhatsApp history** into its own store by default.
  Measured at roughly 1.3 KB per historical message and 4 KB per contact ever seen —
  one test number had cached 19,471 messages to serve a product that had used 41 of
  them. Nothing reads that history; conversation context comes from Postgres. Applies
  to newly created sessions.
- Backups no longer archive the WAHA message store, keep 7 days instead of 14, and
  write a single compressed archive per night.

### Fixed

- **A provider failure no longer discards the customer's message.** The whole turn
  ran in one transaction, so an LLM outage or exhausted quota rolled back the inbound
  message, the conversation, the handoff and the notification, while the "a customer
  needs a human" email had already been sent. The owner got an alert and an empty
  inbox, and Redis-keyed dedupe then dropped WhatsApp's redelivery, losing the message
  for good. The inbound message is now committed before the model is called.

- **`alembic upgrade head` failed on any fresh database.** Migration `0001` builds the
  schema from the current models, so `0007`'s unguarded `add_column` collided with
  columns that already existed, aborting the upgrade. Every new deploy would have
  failed at this step.
- **The daily send cap and warm-up ceiling were not enforced on bot replies** — the
  overwhelming majority of outbound traffic. Manual replies and booking reminders
  honoured them; the pipeline passed a default. `pacing` is now a required argument on
  the send gateway so it cannot silently default again.
- **AI cost was priced against the wrong model** for any tenant configured through the
  nested `providers` map, usually recording $0.00 because the wrong model name misses
  the pricing table. Pricing and provider construction now share one resolver.

### Security

- MinIO's host ports are bound to localhost instead of every interface.
- Application containers read their environment from `${QONVO_ENV_FILE}`, so a second
  stack cannot silently run on production's JWT, Fernet and WAHA secrets.

[Unreleased]: https://github.com/AliasgherBS/qonvo/commits/dev
[0.9.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.9.0
[0.10.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.10.0
[0.10.1]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.10.1
