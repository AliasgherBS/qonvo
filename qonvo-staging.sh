#!/bin/bash
# Qonvo staging stack — a second, isolated copy beside production on this box.
#
# Isolation comes from the compose project name: `-p qonvo-staging` namespaces
# every container, network and volume, so staging gets its own Postgres data,
# Redis, WAHA sessions and MinIO bucket. Host ports come from .env.staging.
#
# Production is untouched by every command here. Nothing in this script names a
# production container, volume or port.
#
#   ./qonvo-staging.sh up        build + start (idempotent)
#   ./qonvo-staging.sh migrate   alembic upgrade head against staging
#   ./qonvo-staging.sh seed      dev tenant + owner + admin, prints logins
#   ./qonvo-staging.sh logs      follow api/worker/scheduler
#   ./qonvo-staging.sh ps        what is running
#   ./qonvo-staging.sh down      stop (volumes kept)
#   ./qonvo-staging.sh reset     stop AND DELETE staging data (never production)
set -euo pipefail

cd "$(dirname "$0")"

PROJECT="qonvo-staging"
ENV_FILE=".env.staging"
# Only the services staging needs. Caddy and the compose `dashboard` service are
# left out: the dashboard runs as a host node process, as it does in dev.
SERVICES=(postgres redis minio waha api worker scheduler)

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Create it first:" >&2
  echo "  cp .env $ENV_FILE && cat .env.staging.example >> $ENV_FILE" >&2
  echo "then edit it — every secret and port must differ from production." >&2
  exit 1
fi

# Read a key the way docker does: the LAST assignment wins.
#
# This matters here more than anywhere. The documented way to build
# .env.staging is `cp .env` followed by appending .env.staging.example, so
# every staging override is a *second* assignment of a key production already
# set -- twelve of them, including QONVO_EMAIL_PROVIDER. A guard that read the
# first match would be reading production's value and checking it against
# itself, passing while the container ran on something else entirely.
env_value() {
  grep -E "^$2=" "$1" 2>/dev/null | tail -n 1 | cut -d= -f2- || true
}

# Guard against the one mistake that would matter: a .env.staging that still
# points at production's database port would migrate or reset the real data.
prod_port=$(env_value .env POSTGRES_HOST_PORT)
stage_port=$(env_value "$ENV_FILE" POSTGRES_HOST_PORT)
if [[ -z "$stage_port" || "$stage_port" == "${prod_port:-5433}" ]]; then
  echo "$ENV_FILE must set POSTGRES_HOST_PORT to something other than production's (${prod_port:-5433})." >&2
  exit 1
fi

# The other mistake that would matter, and the reason staging exists at all:
# staging carries production's tenant data often enough that a real email
# provider here mails a real customer. That is why .env.staging.example forces
# QONVO_EMAIL_PROVIDER=log -- but nothing checked it, and the value only ends
# up as `log` because the append happens to come last. One reorder, one hand
# edit at the bottom of the file, and staging is on production's SMTP.
stage_email=$(env_value "$ENV_FILE" QONVO_EMAIL_PROVIDER)
if [[ "$stage_email" != "log" ]]; then
  echo "$ENV_FILE has QONVO_EMAIL_PROVIDER=${stage_email:-<unset>}; staging must be 'log' so it cannot mail a real customer." >&2
  echo "Note that the effective value is the LAST assignment in the file, not the first." >&2
  exit 1
fi

# QONVO_ENV_FILE is what the application containers read (see the env_file
# anchor in docker-compose.yml); --env-file only feeds interpolation. Both are
# needed, and forgetting the first is how a staging stack ends up running on
# production's JWT, Fernet and WAHA secrets.
dc() {
  QONVO_ENV_FILE="$ENV_FILE" docker compose -p "$PROJECT" --env-file "$ENV_FILE" "$@"
}

case "${1:-up}" in
  up)
    dc up -d --build "${SERVICES[@]}"
    echo "✓ staging up  (api on 127.0.0.1:$(grep -E '^API_HOST_PORT=' "$ENV_FILE" | cut -d= -f2))"
    echo "  next: ./qonvo-staging.sh migrate && ./qonvo-staging.sh seed"
    ;;
  migrate)
    # Run inside the api container so it uses the staging compose network.
    dc run --rm api alembic upgrade head
    ;;
  seed)
    dc run --rm api python scripts/seed_dev.py
    ;;
  logs)
    dc logs -f --tail=100 api worker scheduler
    ;;
  ps)
    dc ps
    ;;
  down)
    dc down
    ;;
  reset)
    read -r -p "Delete ALL staging data (volumes)? Production is untouched. [y/N] " ok
    [[ "$ok" == "y" || "$ok" == "Y" ]] || { echo "aborted"; exit 1; }
    dc down -v
    echo "✓ staging volumes removed"
    ;;
  *)
    echo "usage: $0 {up|migrate|seed|logs|ps|down|reset}" >&2
    exit 1
    ;;
esac
