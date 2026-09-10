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

## The two environments (this is the important section)

Since **2026-09-10** there are two, and they are on different machines. Almost every
stale instruction in this project comes from before that split.

| | **Production** | **Staging** |
|---|---|---|
| Runs on | netcup VPS, `159.195.253.176` | **this machine**, in Docker + a host node process |
| Install path | `/opt/qonvo`, checked out at a **release tag** | `~/qonvo`, your working tree |
| Public at | `qonvo.org` · `www` · `api.qonvo.org` | `dev.qonvo.org` · `dev-api.qonvo.org` |
| Reached via | **Caddy** + real A records + Let's Encrypt | **Cloudflare Tunnel** (`~/.cloudflared/config.yml`) |
| Dashboard | the compose `dashboard` service | host node process on `3012` |
| API | compose `api`, behind Caddy | compose `api` on `8010` |
| Email | ZeptoMail SMTP, real | `log` — it can never mail a customer |
| Deployed by | **GitHub Actions, on a release tag** | you, by rebuilding locally |
| Data | 3 real tenants | its own database, own volumes, own secrets |

**The Cloudflare Tunnel was not retired, it was repurposed.** It fronts staging only.
Production stopped going through it the moment DNS moved to A records.

### How code reaches production

```
feature branch  ->  PR into dev  ->  CI (.github/workflows/ci.yml)
                                      |
                    auto-merge into dev when every job is green
                                      |
                    ./scripts/release.sh X.Y.Z   (runs every gate again, tags)
                                      |
                    git push origin main dev && git push origin vX.Y.Z
                                      |
                    Deploy workflow fires ON THE TAG -> ssh -> /opt/qonvo/deploy.sh
                                      |
                    build, switch, health-check, ROLL BACK if /readyz fails
```

- **Never commit directly to `dev` or `main`.** The auto-merge job in `ci.yml` merges
  feature PRs into `dev` itself and deletes the branch.
- **`dev`'s CI badge is permanently stale, by design.** GitHub does not trigger
  workflows for pushes made with `GITHUB_TOKEN`, so the auto-merge commit runs nothing.
  A red X on `dev` usually means "the last *direct* push was red", not "dev is broken".
- **The deploy key is a forced-command key.** It can run `/opt/qonvo/deploy.sh` with a
  `vX.Y.Z` argument and literally nothing else — verified: it refuses a shell, refuses
  `rm -rf`, refuses a branch name, refuses a tag that does not exist. Secrets
  `QONVO_DEPLOY_KEY` and `QONVO_DEPLOY_KNOWN_HOSTS`.
- **Rollback is `workflow_dispatch` on the Deploy workflow with an older tag.** Not a
  revert commit.

### Staging runs under systemd, not tmux

`qonvo-tunnel.service` and `qonvo-dashboard-staging.service` are **user units**
(`~/.config/systemd/user/`), because tmux died once and took staging offline with it
while the Docker containers happily survived.

```bash
systemctl --user status  qonvo-tunnel qonvo-dashboard-staging
systemctl --user restart qonvo-dashboard-staging     # after a staging rebuild
```

Requires `sudo loginctl enable-linger aliasgher` once, or the units stop when your last
terminal closes.

## Dev environment quirks on this machine

This is a **WSL2 box behind CGNAT**, which is why production could never be pointed at
it directly and why the tunnel existed in the first place.

- Host port `3000` is held by an unrelated `evolution-api` container (user's, don't kill).
  WAHA maps to `127.0.0.1:3001`. Set by [`docker-compose.override.yml`](docker-compose.override.yml)
  (dev-only, auto-merged, every bind is `127.0.0.1`).
- Datastores exposed on localhost for host-run migrations/tests: postgres `5433`, redis `6380`,
  api `8000`.
- The dashboard requires standalone mode: `node .next/standalone/server.js` — `next start`
  does nothing when `output: "standalone"` is set. Environment variables must be passed
  explicitly (standalone doesn't load `.env.local` at runtime).
- Dashboard middleware must whitelist `/api/auth/*` — Auth.js's own routes must be public or
  login is a chicken-and-egg lockout.
- **`NEXT_PUBLIC_*` and `INTERNAL_API_URL` are baked at BUILD time**, including the
  `rewrites()` destination, which Next serialises into `routes-manifest.json`. Setting them
  on a container does nothing. The compose `dashboard` service passes them as **build args**.

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

## Credentials

| What | Where | Login |
|---|---|---|
| Production dashboard | https://qonvo.org | real accounts |
| Staging dashboard | https://dev.qonvo.org | `admin@qonvo.dev` — password in `~/qonvo-migration/staging-admin-password.txt` |
| Local dashboard | http://localhost:3012 (staging build) | same as staging |
| WAHA Swagger (local) | http://localhost:3001 | `X-Api-Key` from `.env` |
| Postgres (local dev) | `localhost:5433` | `qonvo_app` / `qonvo` per `.env` |
| Postgres (local staging) | `localhost:5443` | per `.env.staging` |
| Production, anything | SSH `qonvo@159.195.253.176` | key only, **no sudo** |

**`seed_dev.py` does NOT reset an existing password.** It is `if admin is None:` — it
only *creates* accounts that are missing. This doc used to claim otherwise and it cost a
debugging session. To reset one, hash a new password with `app.services.auth.hash_password`
and update the row.

Secrets live in `.env`, `.env.staging` and `dashboard/.env.local*`, all gitignored. Only
the `.example` templates are tracked — and **`docker compose config` prints resolved
secrets to stdout**, so never run it bare when the output is going anywhere.

## Common commands

**Production is deployed by CI. Do not deploy it by hand unless CI is broken.**

```bash
# --- PRODUCTION -------------------------------------------------------------
# The normal path: merge to dev via PR, then cut a release. CD does the rest.
./scripts/release.sh 0.11.3
git push origin main dev && git push origin v0.11.3

# Roll back: re-run the Deploy workflow with an older tag
gh workflow run deploy.yml -f tag=v0.11.2

# Look at production (read-only; the qonvo user has no sudo)
ssh qonvo@159.195.253.176 'cd /opt/qonvo && docker compose ps'
ssh qonvo@159.195.253.176 'cd /opt/qonvo && docker compose logs --tail=50 api'
curl -s https://api.qonvo.org/readyz

# Break-glass manual deploy, only if Actions is down
ssh qonvo@159.195.253.176 '/opt/qonvo/deploy.sh v0.11.3'

# --- STAGING (this machine) --------------------------------------------------
./qonvo-staging.sh up            # docker services
./run-dashboard-staging.sh --build   # rebuild the dashboard (NEXT_PUBLIC_* is build-time)
systemctl --user restart qonvo-dashboard-staging
systemctl --user status  qonvo-tunnel

# --- LOCAL DEV ----------------------------------------------------------------
cd backend && uv run pytest -q && uv run ruff check      # must stay green
cd dashboard && npx tsc --noEmit && npm run lint && npm run verify:brand

# Migrations (owner role)
QONVO_MIGRATIONS_DATABASE_URL="postgresql+asyncpg://qonvo:dev-postgres-pass@localhost:5433/qonvo" \
  uv run alembic upgrade head
```

**Gotchas that have each cost real time:**
- `verify:brand` **rejects em and en dashes** in dashboard sources. Use plain hyphens.
- `rm -rf .next/standalone/.next/static .next/standalone/public` before copying, or stale
  chunks give `ChunkLoadError`.
- **Hard-refresh (Ctrl+Shift+R)** after any frontend restart.
- `.env` files are read **literally** by docker and by `run-dashboard.sh`. An inline `#`
  after a value becomes part of the value. Comments go on their own line.
- `.env.staging` sets `QONVO_EMAIL_PROVIDER` **twice**; last wins. Editing the first one
  silently does nothing.

## Security posture

Full findings: [`docs/SECURITY-AUDIT.md`](docs/SECURITY-AUDIT.md). Capacity and the work
it implies: [`docs/CAPACITY-AND-SCALING.md`](docs/CAPACITY-AND-SCALING.md).

- **The repository is PUBLIC.** The audit assumed it was not, and said the git-history
  rewrite "belongs before the repo is ever public". That moment has passed. What makes it
  survivable is that rotation, not rewriting, is the real remedy: of the **14** secret-shaped
  values in the tracked-`.env` commit (`4a48a52`), **13 are rotated**. The audit's "ten" was
  an undercount.
- **Still live in public history: `QONVO_MINIO_ACCESS_KEY`.** Low severity — it is the
  username half, `QONVO_MINIO_SECRET_KEY` was rotated, MinIO binds to `127.0.0.1` only, and
  nothing in the codebase constructs a MinIO client. Rotate it anyway.
- **Never put a secret in a tracked file**, including docs and test fixtures.
- Both hosts send security headers from **application** middleware, so they survived the
  move from tunnel to Caddy unchanged.
- **`/docs`, `/redoc` and `/openapi.json` are disabled in production** and enabled
  everywhere else, keyed on `settings.environment`.
- The WAHA webhook HMAC is **per session**, stored on the session row.
- **Rotating `QONVO_FERNET_KEY` requires re-encrypting `integrations.encrypted_credentials`
  first.** Swapping it alone leaves every tenant's Google token undecryptable and fails
  silently. This is also why the VPS migration carried the key across byte-identical.
- Production SSH is **key-only**, root login is `prohibit-password`, and the `qonvo` user
  has **no sudo at all**. netcup's VNC console in SCP is the break-glass path.
- Still open: no rate limiting on auth endpoints, backups local-only.

## Infrastructure gotchas (hard-won, 2026-09-10)

- **netcup's firewall is default-DENY per direction once any rule exists for that
  direction.** A single "DROP outbound port 25" rule blocked *all* outbound TCP, which
  took WhatsApp and the LLM offline while the site kept serving and `/readyz` stayed
  green. Any egress rule needs an explicit `ACCEPT` catch-all below it.
- **The netcup Mail Block blocks outbound SMTP**, not inbound. Using a hosted relay does
  not avoid it: your server still dials out to port 465.
- **Debian 13 minimal has no `gpg`.** Docker's documented `curl | gpg --dearmor` line fails
  and leaves an unsigned-repo error pointing at the wrong cause. Use the armored `.asc`
  directly; apt verifies it natively.
- **`cloudflared` cannot manage DNS.** Its only DNS verb is `tunnel route dns`, which
  creates a CNAME *to a tunnel*. Anything else needs the Cloudflare API.
- **A CNAME cannot share a name with an A record.** Converting the tunnel hostnames meant
  editing the existing records in place, not adding new ones.
- **WhatsApp sessions cannot be migrated.** WAHA session state is Signal-protocol key
  material; the database row survives a move but WAHA will 404, and the API turns that into
  a **502**. Repair by recreating the session in WAHA under its existing name and stored
  HMAC — never by deleting the row, because `whatsapp_sessions -> conversations -> messages`
  all cascade.
- **A freshly linked session duplicates messages** while it uploads pre-keys and syncs
  app state. One `sendText`, two deliveries. It settles.

## Session status

- Phases 0-3 complete and live-verified. Billing, staging, voice, agentic skills all shipped.
- **Production migrated to the netcup VPS on 2026-09-10** and is served by Caddy on real
  A records. Data, RLS, Google integrations and knowledge uploads all carried across;
  the WhatsApp number was relinked by QR, which is the one thing that cannot move.
- **CI/CD is closed end to end**: PR -> CI -> auto-merge to `dev` -> `release.sh` -> tag ->
  GitHub Actions deploys production and verifies the public URLs.
- Remaining work: the nine findings in `docs/CAPACITY-AND-SCALING.md` (P2 pool sizes and
  P1 `max_jobs` first), CRM sync, a live voice test with a real STT/TTS key, and rotating
  `QONVO_MINIO_ACCESS_KEY`.
