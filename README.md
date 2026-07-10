# Qonvo

**An AI customer representative that lives on a business's WhatsApp number.** Multi-tenant SaaS:
answers customers 24/7 from the business's own knowledge, in their language, by text and voice, and
takes real actions — bookings, leads, orders, sheet/CRM writes. Fully-managed; the tenant owner
never runs code.

> **New device? Read this file top-to-bottom — you should be running in ~5 minutes without debugging.**
> Deeper context lives in [`DESIGN.md`](DESIGN.md) (locked v2 architecture) and
> [`CLAUDE.md`](CLAUDE.md) (hard-won gotchas + conventions). Product spec:
> [`Qonvo - AI Whatsapp Rep.md`](Qonvo%20-%20AI%20Whatsapp%20Rep.md).

---

## Stack

Python 3.12 · FastAPI · arq (async workers) — Next.js 15 · Auth.js (v5) · Tailwind 4 — Postgres 16 +
pgvector · Redis 7 · MinIO · Caddy · **WAHA** for WhatsApp. One Docker Compose stack, multi-tenant
from day one. AI providers are **config-driven** (OpenAI / OpenRouter / Groq / Gemini via one
OpenAI-compatible adapter).

## Prerequisites

- **Docker + Docker Compose** (the only hard requirement to run the stack).
- For host-side dev (tests, migrations, running the dashboard in watch mode):
  **Python 3.12 + [uv](https://docs.astral.sh/uv/)** and **Node 20+**.

> This is a **private, single-owner repo**: `.env` and `dashboard/.env.local` are **committed with
> working values**, so a fresh clone already has every secret/URL it needs — no guessing. If the repo
> ever stops being private, **rotate every secret in `.env`** (see [Configuration](#configuration)).

---

## Quickstart (fresh clone → running)

```bash
git clone git@github.com:AliasgherBS/qonvo.git
cd qonvo

# 1. Bring up the whole stack. The api container auto-runs DB migrations; the
#    postgres init script auto-creates the three DB roles on first boot.
docker compose up -d --build

# 2. Seed a dev tenant + owner + admin (+ prints a JWT). One-time.
cd backend
uv run python scripts/seed_dev.py         # uses QONVO_* from ../.env
cd ..

# 3. Run the dashboard (dev, host process on :3002 — see note below)
cd dashboard
npm install && npm run build
cp -r public .next/standalone/ && cp -r .next/static .next/standalone/.next/
env $(grep -v '^#' .env.local | xargs) PORT=3002 HOSTNAME=127.0.0.1 AUTH_URL=http://localhost:3002 \
  node .next/standalone/server.js
```

Then open **http://localhost:3002**, log in (below), and link a WhatsApp number from
**Onboarding → Connect** (scan the QR).

### Dev credentials (from `scripts/seed_dev.py`)

| What | URL | Login |
|---|---|---|
| Dashboard (owner) | http://localhost:3002 | `owner@dev.dev` / `dev-password-123` |
| Dashboard (`/admin`) | same | `admin@qonvo.dev` / `dev-admin-123` |
| WAHA Swagger | http://localhost:3001 | header `X-Api-Key: <QONVO_WAHA_API_KEY from .env>` |

### Service ports (dev, via `docker-compose.override.yml`)

| Service | Host | Notes |
|---|---|---|
| API (FastAPI) | `127.0.0.1:8000` | migrations run on container start |
| WAHA | `127.0.0.1:3001` | container's 3000 (host 3000 was taken on the original VPS) |
| Postgres | `127.0.0.1:5433` | for host-run migrations/tests |
| Redis | `127.0.0.1:6380` | |
| MinIO | `127.0.0.1:9000` / `:9001` | object storage + console |
| Dashboard | `127.0.0.1:3002` | host process in dev (see below) |

> **Dashboard note:** Compose *has* a `dashboard` service (used for a fully-containerized run), but
> in dev we run it as a **host Node process in standalone mode** — `next start` does nothing when
> `output: "standalone"` is set, and standalone doesn't load `.env.local` at runtime, so env vars are
> passed explicitly (see the Quickstart command). Middleware must whitelist `/api/auth/*`.

---

## Configuration

All backend config is env-driven (`QONVO_*`), loaded from [`.env`](.env) (committed). Reference with
inline docs: [`.env.example`](.env.example). Dashboard config: [`dashboard/.env.local`](dashboard/.env.local)
(committed) / [`dashboard/.env.example`](dashboard/.env.example).

**Required for the core bot to work** (already set in `.env`):
- `QONVO_LLM_PROVIDER` / `QONVO_LLM_MODEL` / `QONVO_LLM_API_KEY` and the `QONVO_EMBEDDING_*` triple —
  without a real LLM+embedding key the bot can't reply or index knowledge.
- Three Postgres role URLs (`QONVO_DATABASE_URL` app, `QONVO_MIGRATIONS_DATABASE_URL` owner,
  `QONVO_SYSTEM_DATABASE_URL` system) + matching `*_PASSWORD`s.
- `QONVO_JWT_SECRET`, and a **real** `QONVO_FERNET_KEY` (a placeholder here silently breaks integration
  credential encryption — generate with
  `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`).
- `QONVO_WAHA_API_KEY` / `QONVO_WAHA_HMAC_SECRET`, MinIO creds.

**Optional feature keys** (features cleanly disable if unset):
- **Integrations** (Calendar/Sheets): a Google **service-account** JSON in
  `QONVO_GOOGLE_SERVICE_ACCOUNT_JSON`, or per-tenant in the dashboard → the tenant shares their
  Calendar/Sheet with the service-account email (no OAuth).
- **Voice**: `QONVO_STT_API_KEY` (Groq Whisper works; Gemini has no audio endpoints) for voice-in;
  `QONVO_TTS_API_KEY` (OpenAI/Uplift — **Groq has no TTS**) for voice-out. Without TTS the bot replies
  in text. Toggle per tenant in Settings → Voice.
- **Email** alerts: `QONVO_EMAIL_PROVIDER` = `log` (dev), `resend`, or `smtp`.

---

## Common commands

```bash
# Backend tests + lint (must stay green)
cd backend && uv run pytest -q && uv run ruff check

# Migrations (owner role)
QONVO_MIGRATIONS_DATABASE_URL="postgresql+asyncpg://qonvo:<owner-pass>@localhost:5433/qonvo" \
  uv run alembic upgrade head

# Rebuild + restart backend services after code changes
docker compose up -d --build api worker scheduler

# IMPORTANT: env changes need --force-recreate (plain `restart` won't reload .env)
docker compose up -d --force-recreate api worker

# Re-seed dev tenant/owner/admin + mint a fresh JWT
cd backend && uv run python scripts/seed_dev.py
```

---

## Feature status

| Phase | Status |
|---|---|
| **0 — Foundation** (Docker stack, tenancy + RLS, WAHA client, QR onboarding, HMAC webhooks) | ✅ live-verified |
| **1 — Base offering** (RAG + grounded replies, persona/language, business hours, takeover inbox, knowledge manager, ops console) | ✅ live-verified |
| **2 — Voice VAS** (STT in / TTS out, multilingual; per-tenant voice mode) | ✅ built; STT live-verified with Groq (TTS needs an OpenAI/Uplift key) |
| **3 — Agentic VAS** (Google Calendar bookings, Sheets append, live lookups, availability, orders, payment-details, capped booking reminders, analytics, email alerts, `/metrics`) | ✅ built + live-verified |
| **4 — Scale/enterprise** (team seats, white-label, billing, official Cloud API) | ⬜ future |

Remaining: CRM sync (want), a live voice round-trip with a TTS key, Phase 4.

## Layout

```
Qonvo/
├─ README.md · DESIGN.md · CLAUDE.md · Qonvo - AI Whatsapp Rep.md
├─ docker-compose.yml · docker-compose.override.yml (dev ports) · Caddyfile
├─ .env (committed) · .env.example · scripts/postgres-init/01-app-role.sh
├─ backend/                (FastAPI + arq)
│  ├─ app/api/  core/  providers/  integrations/  agent/  skills/  waha/  services/  workers/
│  ├─ app/models/ + app/alembic/versions/ (0001 schema+RLS · 0002 platform · 0003 orders+payments)
│  ├─ scripts/seed_dev.py · tests/
└─ dashboard/              (Next.js 15 App Router, Tailwind 4, Auth.js v5)
```

## Non-negotiables (see CLAUDE.md for the full list)

- **Three Postgres roles** make RLS real: `qonvo` (owner/migrations), `qonvo_app`
  (NOSUPERUSER, NOBYPASSRLS — all request/worker code), `qonvo_system` (BYPASSRLS — trusted
  cross-tenant paths only). `FORCE ROW LEVEL SECURITY` on every tenant table.
- **A migration creating a new table must `GRANT` DML to `qonvo_app`/`qonvo_system`** — the owner's
  tables don't inherit the superuser's default privileges (see migration 0003).
- **WhatsApp:** accept both `@c.us` and `@lid` senders; never set a global WAHA webhook alongside
  per-session ones; the send gateway fingerprints its own echoes to avoid self-takeover.
- **Reactive 1:1 replies only.** The single bot-initiated outbound is capped booking reminders (§5.7).
