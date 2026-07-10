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
| Dashboard (`/admin`) | same | `admin@qonvo.dev` / `dev-admin-123` |
| WAHA Swagger | http://localhost:3001 | `X-Api-Key: dev-waha-key-change-me` |
| Postgres | `localhost:5433` | app: `qonvo_app`/`dev-app-pass` · owner: `qonvo`/`dev-postgres-pass` |

All in [`.env`](.env). **This is a private, single-owner repo, so `.env` (and
`dashboard/.env.local`) are intentionally committed** with working values — a new device is
pick-up-and-go. Only deps/build/caches are gitignored (see `.gitignore`). **If the repo ever stops
being private/solo, rotate every secret in `.env` and switch it back to gitignored.**

## Common commands

```bash
# Backend tests (must stay green — 106 passing)
cd backend && uv run pytest -q && uv run ruff check

# Migrations (owner role)
QONVO_MIGRATIONS_DATABASE_URL="postgresql+asyncpg://qonvo:dev-postgres-pass@localhost:5433/qonvo" \
  uv run alembic upgrade head

# Rebuild + restart services after backend changes
docker compose up -d --build api worker scheduler

# Dashboard (dev, host process)
cd dashboard && npm run build && cp -r public .next/standalone/ && \
  cp -r .next/static .next/standalone/.next/ && \
  env $(cat .env.local | xargs) PORT=3002 HOSTNAME=0.0.0.0 \
    node .next/standalone/server.js

# Seed / re-mint owner+admin+JWT
cd backend && QONVO_SYSTEM_DATABASE_URL=... QONVO_JWT_SECRET=... \
  uv run python scripts/seed_dev.py
```

## Session status right now

- Phase 0 (foundation) ✅ and Phase 1 (base offering: RAG + grounded replies + auth + inbox
  with takeover + knowledge manager + ops console) ✅ — both live-verified against a real
  WhatsApp number using Gemini as the LLM/embedding provider.
- Phase 3 (agentic VAS) — **substantially complete + live-verified** against a real Google account
  (SA `qonvo-bot@fastapi-cloudrun-454710`, calendar `alihuzezzy@gmail.com`, a Sheets doc):
  - **Skills:** `book_appointment`, `append_to_sheet`, `check_availability`, `lookup_sheet`,
    `take_order` (→ `orders` table), `share_payment_details`. Gated by `requires_integration`
    (Google connected) and `requires_config_key` (e.g. payment_details set).
  - **Google auth = service-account only** (tenant shares Calendar/Sheet with the SA email — no
    OAuth); per-tenant keys Fernet-encrypted in `integrations`, system default
    `QONVO_GOOGLE_SERVICE_ACCOUNT_JSON`. Owner UI `/integrations`.
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
- **Gotchas locked in:** (1) dev `.env` `QONVO_FERNET_KEY` was a placeholder → real key now (local,
  gitignored). (2) A migration-owner-created table does NOT inherit the superuser's DEFAULT
  PRIVILEGES — new tables need explicit `GRANT … TO qonvo_app, qonvo_system` in the migration
  (see 0003). (3) Sheets: quote bare tab names in A1 ranges; append with `RAW` (USER_ENTERED
  evaluates `+`/`=` → corrupts phones + formula-injection risk).
- All four tracks (Phases 0–3 + Phase 2 voice) are now built; remaining work is CRM sync (want),
  a live voice test with a real STT/TTS key, and Phase 4 (team seats, white-label, billing).
- WhatsApp session `dev-tenant-main` is linked to the user's demo number; unlink from
  WhatsApp → Settings → Linked devices when done.
