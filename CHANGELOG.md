# Changelog

All notable changes to Qonvo. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Branch flow: work lands on a feature branch, merges to `dev`, and is released to `main`
with an annotated `vX.Y.Z` tag. `Unreleased` below is what sits on `dev` awaiting a
release. See [CONTRIBUTING.md](CONTRIBUTING.md).

## [Unreleased]

### Added

- [docs/DEPLOYMENT-AND-COSTS.md](docs/DEPLOYMENT-AND-COSTS.md): measured resource
  profile, per-tenant storage model, VPS provider comparison at September 2026 rates,
  and the self-hosted versus managed Postgres decision. AI costs are catalogued
  **provider-agnostically** — 18 language models, 11 TTS and 13 STT providers, each
  normalised to this deployment's measured cost per 1,000 replies — plus a section on
  what can actually be bought and paid for from Pakistan.

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
