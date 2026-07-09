#!/bin/bash
# Creates the non-superuser application role on first database init.
#
# WHY: the role in POSTGRES_USER is a superuser and Postgres superusers BYPASS
# row-level security entirely (even with FORCE ROW LEVEL SECURITY). The app
# must therefore connect as this restricted role for tenant isolation (§3 of
# DESIGN.md) to actually be enforced. Migrations keep running as the owner.
#
# Runs via docker-entrypoint-initdb.d on a fresh data volume only.
set -euo pipefail

: "${APP_DB_USER:=qonvo_app}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be set}"
: "${SYSTEM_DB_USER:=qonvo_system}"
: "${SYSTEM_DB_PASSWORD:?SYSTEM_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    -- Tenant-scoped app role: RLS fully enforced.
    CREATE ROLE ${APP_DB_USER} LOGIN PASSWORD '${APP_DB_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

    -- Trusted system role: native BYPASSRLS for cross-tenant server paths
    -- (webhook tenant resolution, scheduler fleet scans). DML only — no DDL.
    CREATE ROLE ${SYSTEM_DB_USER} LOGIN PASSWORD '${SYSTEM_DB_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;

    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${APP_DB_USER}, ${SYSTEM_DB_USER};
    GRANT USAGE ON SCHEMA public TO ${APP_DB_USER}, ${SYSTEM_DB_USER};

    -- Tables created later by the owner (alembic migrations) automatically
    -- get DML grants for both roles.
    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_DB_USER}, ${SYSTEM_DB_USER};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO ${APP_DB_USER}, ${SYSTEM_DB_USER};

    -- Cover anything that already exists at init time.
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
        TO ${APP_DB_USER}, ${SYSTEM_DB_USER};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
        TO ${APP_DB_USER}, ${SYSTEM_DB_USER};
SQL
