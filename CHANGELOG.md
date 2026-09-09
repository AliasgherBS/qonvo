# Changelog

All notable changes to Qonvo. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Branch flow: work lands on a feature branch, merges to `dev`, and is released to `main`
with an annotated `vX.Y.Z` tag. `Unreleased` below is what sits on `dev` awaiting a
release. See [CONTRIBUTING.md](CONTRIBUTING.md).

## [Unreleased]

## [0.11.0] - 2026-09-09

### Added

- **A readable audit log in the ops console.** Every state-changing admin action was
  recorded and none of it could be read without psql. There is now a reader with
  tenant, actor and action filters, paged on the server and ordered with `id` as a
  tiebreak so paging cannot repeat or skip a row. The three actor shapes that had
  accumulated are reconciled, and an impersonated action shows who was really behind
  it rather than reading as the customer's own.

- **A second factor on the `qonvo_admin` account**, enrolled by scanning a QR rather
  than typing a secret. The encoder is checked by a gate that rasterises the QR and
  decodes it with a different library, because a QR that renders is not a QR that
  scans, and a wrong one fails at the moment somebody is locked out.

- **"Improve with AI" on custom instructions.** Rewrites what an owner wrote into
  something the prompt builder can honour, and says what it changed.

- **Email verification at signup**, and an owner can see and revoke their own
  sessions.

- **Plan, trial and impersonation controls in the console**, so support does not need
  psql for the three things it needed it for most.

### Changed

- **The rep no longer promises what the business never offered.** The system prompt
  instructed the model to reassure and offer a callback, so it was manufacturing
  commitments the owner had never made — a customer was told "our team will call you
  back within the hour" when nobody was going to call. The prompt guard-rails; the
  call to action belongs to the owner. Verified live: asked for a branch that does not
  exist and a callback, the rep now says it does not have that detail rather than
  inventing either.

- **An owner's instructions can no longer contradict the tools the rep has.** A
  connected integration wins over prose that argues with it, and an instruction that
  contradicts a live capability is surfaced to the owner instead of being silently
  obeyed or silently dropped.

- **Skills are described in the prompt, not only offered as tools.** Six were offered
  on every turn and chosen on none. The one the model did use, `human_handoff`, was
  the only one named in the prompt text.

- **One date format across the product** (`4 Sept 2026`), one timezone per tenant, and
  the inbox names the customer.

### Fixed

- **Marking a customer paid now grants what they paid for.** The console wrote
  `tenants.plan` while entitlements kept whatever the previous plan allowed, so an
  operator who took a bank transfer left the customer capped at the trial's 300
  messages while the console reported a paid plan. Plan changes go through
  `apply_plan`, which derives entitlements from the catalogue, and the old field is
  kept only so it can be refused with an explanation.

- **A refreshed knowledge source stops billing for text it no longer holds.**
  Re-ingesting tombstoned the previous chunks instead of deleting them. Every reader
  filtered those out except the character quota, which counted them all — so
  refreshing a page charged the business again, permanently, and the owner's own page
  and the quota disagreed by exactly the overcharge. Nothing purged them either.

- **A dead ingestion job can no longer look alive.** A failure at COMMIT happens as
  the transaction context exits, after any handler inside it, so a source could log
  "ingested" and then fail with nothing marked. The failure is now caught outside the
  session, recorded on a fresh connection, and shown to the owner with a readable
  reason instead of a bare "error".

- **A number that stops answering tells its owner.** One sat at FAILED for about
  twenty hours, reported accurately on Fleet Health and nowhere else: the only alert
  hung off the recovery budget, and that session had no credentials to restart into,
  so nothing retried, nothing exhausted, and nobody was told. Owners are now alerted
  three minutes into an outage, once per episode, and the give-up notice half an hour
  later says what changed rather than repeating the first.

- **Voice is metered from what the provider reports**, not from the size of the file.
  A byte-rate assumption of 2,000 B/s applied to a 48,000 B/s WAV over-reported a
  ten-second note by twenty-four times.

- **Prompt-cache hit rate on every message.** The tool array was built from a `set`,
  so several thousand bytes at the front of every request reshuffled between calls
  and the cached prefix never matched.

- **One usage number, one meaning.** The same 89 stored seconds read as "2 min of 5"
  on the owner's page and as 89 on the admin endpoint, and neither said which unit or
  whose usage it was.

- **Fleet Logout no longer sits next to Restart as an equal.** It destroys the
  WhatsApp pairing and needs a physical phone to undo, so it now asks for the business
  name in full and points at Restart as the thing you probably meant.

### Security

- **A 422 no longer hands back what it rejected.** pydantic sets `input` to the whole
  submitted body for a `missing` error, so any route with a required field returned
  every other field: `POST /api/auth/signup` came back with a new customer's plaintext
  password, `reset-password` with the reset token, the admin config route with a
  tenant's bank details, and the inbox reply route with the message a business was
  sending a customer. Fixed app-wide rather than per router, because a curated list of
  "endpoints that carry secrets" missed four and then a fifth.

- **Staff seats could cancel the subscription, change the plan, turn the rep off and
  rewrite the payment details** the rep reads out to customers. `require_owner`
  existed and was used in two modules out of twenty-one. Asserted now as a property of
  the route table rather than per endpoint, so a new route is owner-only until it is
  deliberately listed.

- **Ten ordinary logins no longer lock out an office.** The per-address counter
  counted successes and was never cleared, so ten correct logins from one connection
  refused the eleventh for fifteen minutes — which in this market means a shared
  office line, or a stranger behind the same CGNAT address.

- **Every per-address rate limit was bypassable with one header, on production.**
  `X-Forwarded-For` is caller-supplied and Cloudflare only adds to it, so rotating it
  meant no counter ever filled. That covered the five-signups-per-hour cap, which is
  the only thing between a script and unlimited tenant rows. Now keyed on
  `CF-Connecting-IP`, confirmed against production rather than assumed.

- **A stranger can no longer lock you out of your own business.** Eleven deliberate
  failures on a known address refused the owner's correct password for fifteen
  minutes, from anywhere, repeatably. Failures are now counted per (account, address)
  with a much larger backstop for the distributed case.

- **Tokens can be revoked, so signing out signs you out.** A session had no `jti`, so
  logging out cleared the browser's copy and left the credential valid for the rest of
  its 24 hours.

- **A real password policy**, screened against known breaches, with the work factor
  pinned so it cannot silently weaken.

- **The server refuses to fetch a URL that points inside our own network**, on every
  resolved address and again on each redirect hop.

- **Google Sheets picking works**, and a blocked frame now fails with a sentence
  naming the origin instead of hanging: `docs.google.com` was never in `frame-src`.


## [0.10.2] - 2026-09-08

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
[0.10.2]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.10.2
[0.11.0]: https://github.com/AliasgherBS/qonvo/releases/tag/v0.11.0
