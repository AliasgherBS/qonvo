# Qonvo — Context for Claude

**Product.** Multi-tenant SaaS: an AI customer rep on a business's WhatsApp number.
Answers 24/7 from the business's own knowledge, in the customer's language, by text and voice,
and takes actions (bookings, leads, CRM/sheet writes). Fully-managed — the tenant owner never
runs code.

**Authoritative documents.**
- [`DESIGN.md`](DESIGN.md) — v2 technical design (locked, live-verified). Read this first for
  any architecture question. Section refs (`§5.1`, `§5.5`…) throughout the code refer to it.
- [`Qonvo - AI Whatsapp Rep.md`](Qonvo%20-%20AI%20Whatsapp%20Rep.md) — product spec.

## Stack (locked)

Python 3.12 + FastAPI + arq (async workers) · Next.js 15 + Auth.js + Tailwind 4 · Postgres 16 +
pgvector · Redis 7 · MinIO · Caddy · **WAHA** for WhatsApp
(`devlikeapro/waha:latest-2026.6.2` — engine-prefixed tag; latest-* = WEBJS build).
Everything runs as one Docker Compose stack on a single VPS, built multi-tenant from day one.

**AI providers are config-driven, not hard-coded.** One OpenAI-compatible adapter covers OpenAI,
OpenRouter, Groq, Gemini (via its OpenAI-compat endpoint), and any custom `base_url`. Selected
per-tenant with a system default (`QONVO_LLM_PROVIDER` / `QONVO_LLM_MODEL` / `QONVO_LLM_API_KEY`
and the `QONVO_EMBEDDING_*` triple).

## Multi-tenancy & security (non-negotiable)

- **Three Postgres roles** (superusers bypass RLS, so role separation is what makes RLS real):
  `qonvo` (owner, migrations only, `QONVO_MIGRATIONS_DATABASE_URL`) ·
  `qonvo_app` (NOSUPERUSER, NOBYPASSRLS, all request/worker code, `QONVO_DATABASE_URL`) ·
  `qonvo_system` (BYPASSRLS, trusted cross-tenant paths only — webhook tenant resolution,
  scheduler, `QONVO_SYSTEM_DATABASE_URL`).
- `FORCE ROW LEVEL SECURITY` on every tenant-scoped table. Policies use
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid` — pooled connections return `''`,
  not NULL, for unset GUCs. Deliberately no GUC-based bypass in policies (any session can
  `set_config` — that would be an escape hatch).
- Roles auto-created by [`scripts/postgres-init/01-app-role.sh`](scripts/postgres-init/01-app-role.sh) on first init.

## WhatsApp facts (hard-won, live-verified)

- **Modern WhatsApp accounts message from `@lid` (Linked ID), not just `@c.us`** — the
  processable-chat filter must accept both.
- **Never configure a WAHA global webhook (`WHATSAPP_HOOK_URL`) alongside per-session webhooks
  on the same URL.** WAHA dedupes by URL; the unsigned global hook shadows the signed session
  hook → every delivery 401s.
- **Send-gateway echoes back as `fromMe`** just like the owner replying from their phone. The
  gateway must fingerprint every send (Redis `waha:ownsend:<id>`, 24h TTL) and the webhook
  must skip its own echoes — otherwise the bot triggers implicit takeover on itself and
  silences (§5.5).
- On a `fromMe` message, the customer chat is `payload.to`, not `payload.from`.
- Reactive 1:1 replies only. Bulk/broadcast is the ban-risk behavior and is out of scope
  until an official Cloud API provider is added; capped booking reminders (§5.7) are the only
  bot-initiated outbound.

## arq (Redis) queues

Scheduler and worker are **separate consumer processes** and must use **different queue names**
(`arq:scheduler` vs the default). If they share the queue, the scheduler grabs worker jobs
(e.g. `ingest_knowledge_source`) and drops them as *function not found*.

## Public access (live since 2026-09-06)

`qonvo.org` is live, served from **this machine** through a **Cloudflare Tunnel**
(`cloudflared tunnel run qonvo`, in the `cloudflared` tmux window). The tunnel dials
outward, so nothing is port-forwarded and no public IP is needed — this box sits behind
CGNAT and could never have been pointed at directly.

| Host | Serves | Local target |
|---|---|---|
| `qonvo.org` | landing page + dashboard | `localhost:3002` (host node process) |
| `api.qonvo.org` | FastAPI | `localhost:8000` |

Routing lives in `~/.cloudflared/config.yml`. **The dashboard and API are now separate
origins**, so `QONVO_CORS_ORIGINS` must contain `https://qonvo.org` or every browser call
fails while curl keeps working.

Moving to a VPS later changes only where DNS points; every application setting stays as
it is. Runbook, including rollback: [`docs/GOING-LIVE-ON-A-DOMAIN.md`](docs/GOING-LIVE-ON-A-DOMAIN.md).

## Dev environment quirks on this VPS

- Host port `3000` is held by an unrelated `evolution-api` container (user's, don't kill).
  WAHA maps to `127.0.0.1:3001`. Set by [`docker-compose.override.yml`](docker-compose.override.yml)
  (dev-only, auto-merged).
- Datastores exposed on localhost for host-run migrations/tests: postgres `5433`, redis `6380`,
  api `8000`.
- Dashboard runs as a **host node process on port 3002** (not the compose service in dev). It
  requires standalone mode: `node .next/standalone/server.js` — `next start` does nothing when
  `output: "standalone"` is set. Environment variables must be passed explicitly (standalone
  doesn't load `.env.local` at runtime).
- Dashboard middleware must whitelist `/api/auth/*` — Auth.js's own routes must be public or
  login is a chicken-and-egg lockout.

## Provider gotchas

- Gemini's `text-embedding-004` no longer exists (404). Use `gemini-embedding-001`.
- Gemini's default embedding output is 3072 dims; our pgvector column is 1536. The adapter
  pins `dimensions=EMBEDDING_DIM` to force a match.
- Groq has **no embeddings endpoint**. A single Gemini key covers both LLM and embeddings via
  the OpenAI-compat surface.
- Gemini can omit `usage` from chat responses — parse defensively (`... or 0`, not `.get(..., 0)`).

## Layout

```
Qonvo/
├─ DESIGN.md · Qonvo - AI Whatsapp Rep.md
├─ docker-compose.yml · docker-compose.override.yml (dev) · Caddyfile · .env.example
├─ scripts/postgres-init/01-app-role.sh  ▸ backup.sh
├─ backend/                (FastAPI + arq)
│  ├─ app/api/             REST routes (owner + /admin) + webhook ingress
│  ├─ app/core/            config, security (HMAC, JWT, argon2, Fernet), tenancy/RLS
│  ├─ app/providers/       LLM/embedding adapters + registry (config-driven)
│  ├─ app/agent/           debounce, RAG, ingestion, pipeline seams
│  ├─ app/skills/          registry, capture_lead, human_handoff (idempotent)
│  ├─ app/waha/            WAHA REST client + paced send gateway
│  ├─ app/services/        auth, takeover state machine, notifications, admin
│  ├─ app/workers/         arq worker + scheduler (separate queues)
│  ├─ app/models/ + alembic/versions/ (0001 = schema+RLS, 0002 = Phase 1)
│  └─ scripts/seed_dev.py  (dev tenant + owner + qonvo_admin, prints JWT)
└─ dashboard/              (Next.js 15 App Router, Tailwind 4, Auth.js)
```

## Dev credentials (seeded by `scripts/seed_dev.py`)

| What | Where | Login |
|---|---|---|
| Dashboard | http://localhost:3002 | `owner@dev.dev` / `dev-password-123` |
| Dashboard (`/admin`) | same | `admin@qonvo.dev` / **rotated — no longer `dev-admin-123`**; re-run `seed_dev.py` to reset it |
| WAHA Swagger | http://localhost:3001 | `X-Api-Key: dev-waha-key-change-me` |
| Postgres | `localhost:5433` | app: `qonvo_app`/`dev-app-pass` · owner: `qonvo`/`dev-postgres-pass` |

All in [`.env`](.env), which is **gitignored** (`a80ca3a` stopped tracking secrets). Only the
templates are tracked: [`.env.example`](.env.example), `.env.staging.example`,
`dashboard/.env.local.example`. A fresh clone therefore has no working `.env` — copy the
templates and fill them in, or carry the files across out of band.

The staging stack keeps its own `.env.staging` (also gitignored) with **different** secrets,
ports and `QONVO_EMAIL_PROVIDER=log`, so it can never mail a real customer.

## Common commands

**Use the committed scripts — don't hand-roll the dashboard start line.**

```bash
# Rebuild + restart EVERYTHING after code changes (the usual one)
cd ~/qonvo && ./qonvo-redeploy.sh

# Bring the whole stack up from scratch (after a reboot / tmux gone)
cd ~/qonvo && ./qonvo-up.sh          # docker + tmux(dashboard, cloudflared) + a public health check

# Backend tests (must stay green — 286 passing, 8 skipped)
cd backend && uv run pytest -q && uv run ruff check

# Staging: a second, fully isolated stack on this box (own DB/Redis/WAHA/volumes)
cd ~/qonvo && ./qonvo-staging.sh up && ./qonvo-staging.sh migrate && ./qonvo-staging.sh seed
#   api 8010 · postgres 5443 · redis 6390 · waha 3011 · minio 9010/9011
#   Integration tests belong HERE, not against 5433 — they create/delete real tenants.

# Migrations (owner role)
QONVO_MIGRATIONS_DATABASE_URL="postgresql+asyncpg://qonvo:dev-postgres-pass@localhost:5433/qonvo" \
  uv run alembic upgrade head

# Piece-by-piece: backend only
docker compose up -d --build api worker scheduler

# Piece-by-piece: frontend only (respawns the tmux window)
cd ~/qonvo/dashboard && export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && \
  npm run build && \
  rm -rf .next/standalone/.next/static .next/standalone/public && \
  cp -r public .next/standalone/ && cp -r .next/static .next/standalone/.next/ && \
  tmux respawn-window -k -t qonvo:dashboard "~/qonvo/run-dashboard.sh 2>&1 | tee /tmp/qonvo-dashboard.log"

# Restart only, no rebuild (nothing changed)
docker compose restart api worker scheduler
tmux respawn-window -k -t qonvo:dashboard "~/qonvo/run-dashboard.sh"

# Seed / re-mint owner+admin+JWT
cd backend && QONVO_SYSTEM_DATABASE_URL=... QONVO_JWT_SECRET=... \
  uv run python scripts/seed_dev.py
```

**Deploy gotchas (hard-won):**
- `rm -rf .next/standalone/.next/static .next/standalone/public` before copying is
  **required** — stale chunks left behind cause `ChunkLoadError` in the browser.
- **Hard-refresh (Ctrl+Shift+R)** after every frontend restart; a rebuild changes
  chunk hashes and the browser caches the old HTML.
- `run-dashboard.sh` parses env with `grep -v '^#' .env.local | xargs`, so comment
  lines in `.env.local` are fine but **inline `#` comments after a value are not**.
- `NEXT_PUBLIC_*` vars are baked in at **build** time — a bare restart won't pick
  them up, you need `npm run build`. Server-side vars (`AUTH_URL`, `AUTH_GOOGLE_*`)
  only need a restart.

## Session status right now

- Phase 0 (foundation) ✅ and Phase 1 (base offering: RAG + grounded replies + auth + inbox
  with takeover + knowledge manager + ops console) ✅ — both live-verified against a real
  WhatsApp number using Gemini as the LLM/embedding provider.
- Phase 3 (agentic VAS) — **substantially complete + live-verified** against a real Google account
  (SA `qonvo-bot@fastapi-cloudrun-454710`, calendar `alihuzezzy@gmail.com`, a Sheets doc):
  - **Skills:** `book_appointment`, `append_to_sheet`, `check_availability`, `lookup_sheet`,
    `take_order` (→ `orders` table), `share_payment_details`. Gated by `requires_integration`
    (Google connected) and `requires_config_key` (e.g. payment_details set).
  - **Google auth = per-tenant user OAuth** (service accounts fully removed). Owner clicks
    **Connect Google** on `/integrations`; refresh token Fernet-encrypted in
    `integrations.encrypted_credentials`, non-secret metadata (`granted_scopes`, `account_email`,
    target ids) in `integrations.config` so listing never decrypts. One platform-wide OAuth client
    (`QONVO_GOOGLE_OAUTH_CLIENT_ID`/`_SECRET`/`_REDIRECT_BASE`) also backs **Sign in with Google**.
    **Scopes are all non-sensitive → no Google verification needed:** `calendar.app.created` (Qonvo
    creates a "Qonvo Bookings" calendar on connect) + `calendar.freebusy` (so availability sees the
    owner's *real* busy blocks — `app.created` alone is blind to them and would double-book) and
    `drive.file` for Sheets (valid for `values.append`; the file becomes reachable *because* the
    owner picked it in the Google Picker, so a typed spreadsheet id 404s by design).
  - **Analytics** `GET /api/analytics/summary` + `/analytics` page (live). **Email** owner-alerts
    (config-driven log/resend/smtp; wired to human_handoff). **Metrics** `GET /metrics` (Prometheus,
    hand-rolled, no dep). **Payments** = Settings field, shared verbatim by the skill.
  - **Booking reminders (§5.7)** ✅ — scheduler cron (every 15 min) sends a confirmation + a 24h
    reminder, capped at 2/booking (per-timestamp), business-hours-aware, opt-out via
    `reminder_suppressions` (a "stop" reply suppresses). Verified live with a fake gateway.
  - Remaining Phase 3: CRM sync (want). Chained flows already work via the tool loop.
- **Phase 2 (voice VAS)** ✅ landed (commit 1ad91b7): OpenAI-compat STT (`/audio/transcriptions`) +
  TTS (`/audio/speech`) adapters, `resolve_stt`/`resolve_tts` (return None w/o key → voice off),
  pipeline voice-in (WAHA media → STT → transcript) + voice-out (TTS → `send_voice`), per-tenant
  `voice_reply_mode` (match/always/never) in Settings. **Gemini's OpenAI-compat has NO audio
  endpoints — voice needs a Groq/OpenAI STT/TTS key even when the LLM is Gemini.** Live voice E2E
  still needs that key + a real voice note.
- **Gotchas locked in (2026-09-04 cycle):**
  - `alembic upgrade head` used to **fail on any fresh database**: 0001 builds the schema with
    `create_all` from the *current* models, so 0007's bare `add_column` hit columns that already
    existed. Every new migration that touches an existing table must guard (`sa.inspect`), and
    every new table must `create(..., checkfirst=True)` — 0003/0006/0008 already do.
  - Bot replies passed a bare `SessionPacing()`, so the daily cap and warm-up ceiling were
    unenforced on the majority of traffic while manual replies and reminders honoured them.
    `pacing` is now a **required** argument on the gateway so it cannot silently default again.
  - Cost was priced from the flat `llm_provider/llm_model` columns while `resolve_llm` prefers
    `providers["llm"]` — a tenant configured through the nested map was billed against the wrong
    model (usually $0.00 on a pricing-table miss). Both now call `resolve_llm_identity`.
  - `warmup_stage` was never set by anything: the ORM default was dead code because
    `sessions.py` always passes `body.warmup_stage` explicitly. **A model default is not a
    default when the caller always supplies the field.**
  - WAHA `fullSync` is off by default now (`QONVO_WAHA_FULL_SYNC`). Existing session volumes keep
    their history — only newly created sessions are affected.
- **Gotchas locked in:** (1) dev `.env` `QONVO_FERNET_KEY` was a placeholder → real key now (local,
  gitignored). (2) A migration-owner-created table does NOT inherit the superuser's DEFAULT
  PRIVILEGES — new tables need explicit `GRANT … TO qonvo_app, qonvo_system` in the migration
  (see 0003). (3) Sheets: quote bare tab names in A1 ranges; append with `RAW` (USER_ENTERED
  evaluates `+`/`=` → corrupts phones + formula-injection risk).
- **Google OAuth gotchas (hard-won):**
  - Google's `/revoke` kills the **entire grant** for a client id, not one provider's scopes — so
    revoking on a Sheets disconnect would also break Calendar. `delete_integration` guards it behind
    `other_google_provider_has_token`.
  - An OAuth client left in **Testing** publishing status issues refresh tokens that expire after
    **7 days** — every tenant's bot would die weekly. Must be "In production" (free for
    non-sensitive scopes).
  - `prompt=consent` is mandatory: without it a *re*-connect returns **no** refresh token and you
    silently keep serving the stale one.
  - `JSONBType` has no `MutableDict`, so every `integrations.config` write must **reassign** the
    dict (`config = {**config, ...}`) — in-place mutation is never flushed. And config now mixes
    owner-written with system-written keys, so `upsert_integration` **merges** rather than replaces
    (a PUT of just `timezone` used to wipe `calendar_id`).
  - `FORCE ROW LEVEL SECURITY` applies to the table owner, and the migration role `qonvo` *is* the
    owner — so a bare `UPDATE <tenant_table> SET …` in a migration matches **zero rows**
    (`0004_billing.py:29` is already silently a no-op for this reason).
  - The OAuth callback uses `tenant_session`, **not** `system_session`: its state token was minted
    inside an authenticated request and is single-use (Redis `GETDEL`), so the tenant is already
    established. Unlike the WAHA webhook, it has no cross-tenant lookup to do, and handing an
    unauthenticated public endpoint a BYPASSRLS connection would discard RLS for nothing.
  - The id_token read in `google_oauth.py` is **unverified on purpose** (server-to-server from
    Google's token endpoint, display string only). The one in `services/google_identity.py` comes
    from the browser and gets full JWKS signature + `aud`/`iss`/`exp` verification — never conflate
    the two.
  - **`AUTH_URL` must be set explicitly in `dashboard/.env.local`.** Auth.js host-derivation is
    broken behind a proxy: verified live that the tunnel forwards `Host` *and* `X-Forwarded-Host`
    as the public domain, yet Auth.js still built `https://localhost:3002/api/auth/callback/google`
    (it honoured `X-Forwarded-Proto` but not the host) → `redirect_uri_mismatch` from every device.
    Pinning `AUTH_URL` fixes it. Consequence: SSO from `localhost:3002` finishes on the public
    domain, so the cookie lands there — use email+password locally. **`AUTH_URL`,
    `QONVO_GOOGLE_OAUTH_REDIRECT_BASE`, `QONVO_DASHBOARD_BASE_URL` and the Cloud console redirect
    URIs are all coupled to the public hostname — change one, change all four.**
  - **The two Google redirect URIs live on different hosts**, which is easy to get wrong:
    integrations on the API host (`https://api.qonvo.org/api/integrations/oauth/callback`),
    Sign in with Google on the dashboard host (`https://qonvo.org/api/auth/callback/google`).
    The `/backend` prefix the integrations URI used to carry is **gone**: it existed only while
    one tunnel host fronted the dashboard and proxied `/backend/*` to the API.
  - **`.env` is read by docker as a literal env file, not by a shell.** Inline `#` comments after
    a value and leading spaces become *part of the value* — proved with a throwaway container
    after an edit produced `" https://api.qonvo.org #https://old-host"`. Comments go on their own
    line. (`run-dashboard.sh` has the same constraint for `.env.local`.)
- **Billing (2026-09-04)** ✅ — provider-agnostic subsystem shaped around a merchant of record
  (Paddle/Polar), shipped with a **manual adapter** so it works before any gateway account exists.
  Plan catalogue in code (`app/billing/plans.py`, entitlements only — **prices deliberately live
  with the provider, never in this repo**), `subscriptions` + `billing_events` (migration 0008,
  the latter an idempotency ledger because MoRs retry webhooks), a pure `service_state` gate
  (suspended / trial_expired / past_due-with-7-day-grace / cancelled-but-paid-through), seat
  enforcement on team invites, and `POST /webhooks/billing/{provider}`. Entitlements are
  **derived** from the catalogue by `apply_plan`, so a plan change can never leave a stale quota.
  Design: [`docs/superpowers/specs/2026-09-04-billing-design.md`](docs/superpowers/specs/2026-09-04-billing-design.md).
- **Staging (2026-09-04)** ✅ — `./qonvo-staging.sh` runs a second compose project
  (`qonvo-staging`) beside production: own volumes, own secrets, own ports, email forced to `log`
  so it can never mail a real customer. **The trap it exposed:** compose's `--env-file` only feeds
  *interpolation*; the containers read `env_file:` literally, so a staging stack silently ran on
  production's JWT/Fernet/WAHA secrets until the anchor became `${QONVO_ENV_FILE:-.env}`.
- All four tracks (Phases 0–3 + Phase 2 voice) are built; remaining work is CRM sync (want),
  a live voice test with a real STT/TTS key, an MoR account, and the VPS/domain move.
- WhatsApp session `dev-tenant-main` is linked to the user's demo number; unlink from
  WhatsApp → Settings → Linked devices when done.
