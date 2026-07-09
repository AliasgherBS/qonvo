# Qonvo Backend (Phase 0)

FastAPI backend for Qonvo — an AI customer representative on a business's WhatsApp
number. Phase 0 delivers the foundation: multi-tenant data model with Postgres RLS,
WAHA client + paced send gateway, webhook ingress (HMAC verify, filtering, dedupe,
debounce), and the arq worker/scheduler skeleton with a stubbed agent pipeline.

See [`../DESIGN.md`](../DESIGN.md) for the authoritative spec.

## Requirements

- [uv](https://docs.astral.sh/uv/) with Python 3.12
- Postgres 16 with the `pgvector` extension (use `pgvector/pgvector:pg16`)
- Redis 7

## Setup

```bash
cd backend
uv python install 3.12   # once, if not already present
uv sync                  # creates .venv and installs deps (incl. dev group)
cp ../.env.example ../.env   # then edit the values
```

Generate the two required secrets:

```bash
# Fernet master key (integration-credential encryption)
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# JWT secret
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Database migrations

The initial migration creates the `pgvector` extension, all tables, and enables
Row-Level Security with `tenant_id` policies on every tenant-scoped table.

```bash
uv run alembic upgrade head          # apply migrations
uv run alembic downgrade -1          # roll back one
uv run alembic revision --autogenerate -m "message"   # new migration
```

## Run the API (dev)

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/healthz`. Interactive docs at `/docs`.

## Run the worker

```bash
uv run arq app.workers.worker.WorkerSettings
```

## Run the scheduler

The scheduler is an arq worker with cron jobs (session-health polling every 60s).

```bash
uv run arq app.workers.scheduler.SchedulerSettings
```

## Tests & lint

```bash
uv run ruff check          # lint
uv run ruff format --check # format check
uv run pytest              # tests (fakeredis + aiosqlite; no live services needed)
```

Tests that require a real Postgres (RLS, pgvector) are marked `@pytest.mark.postgres`
and skipped by default. Run them against a live database with:

```bash
QONVO_TEST_DATABASE_URL=postgresql+asyncpg://... uv run pytest -m postgres
```

## Layout

```
app/
  api/        REST routes (webhook ingress, sessions, health)
  core/       config, security (HMAC/JWT/Fernet), tenancy/RLS session
  db/         SQLAlchemy base + async engine/session
  models/     SQLAlchemy 2.0 models (DESIGN.md §11)
  providers/  LLM/STT/TTS/Embedding abstract interfaces (Phase 0: base only)
  waha/       WAHA HTTP client + paced send gateway
  workers/    arq worker, agent pipeline stub, scheduler
  alembic/    migrations (initial: extension + tables + RLS)
tests/        pytest (fakeredis, aiosqlite)
```
