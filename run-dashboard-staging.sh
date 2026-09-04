#!/bin/bash
# Staging dashboard — host node process on 3012, pointed at the staging API.
#
# Builds into .next-staging (via a distinct distDir) so a staging build and a
# production build can coexist: they bake NEXT_PUBLIC_* values in at build time,
# so sharing one .next directory would mean whichever built last wins and the
# other silently serves the wrong API URL and the wrong environment badge.
#
#   ./run-dashboard-staging.sh          serve an existing build
#   ./run-dashboard-staging.sh --build  rebuild first, then serve
set -euo pipefail

cd ~/qonvo/dashboard
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

ENV_FILE=".env.staging.local"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing dashboard/$ENV_FILE — copy $ENV_FILE.example and fill it in." >&2
  exit 1
fi

if [[ "${1:-}" == "--build" ]]; then
  # NEXT_DIST_DIR is read by next.config.ts; the env file supplies the
  # NEXT_PUBLIC_* values that get baked into this build.
  # shellcheck disable=SC2046
  env $(grep -v '^#' "$ENV_FILE" | xargs) NEXT_DIST_DIR=.next-staging npm run build
  # Standalone needs static assets and public/ copied in beside it. Removing
  # them first is required: stale chunks cause ChunkLoadError in the browser.
  rm -rf .next-staging/standalone/.next-staging/static .next-staging/standalone/public
  mkdir -p .next-staging/standalone/.next-staging
  cp -r public .next-staging/standalone/
  cp -r .next-staging/static .next-staging/standalone/.next-staging/
fi

if [[ ! -f .next-staging/standalone/server.js ]]; then
  echo "No staging build yet — run: ./run-dashboard-staging.sh --build" >&2
  exit 1
fi

# shellcheck disable=SC2046
exec env $(grep -v '^#' "$ENV_FILE" | xargs) \
  PORT=3012 HOSTNAME=127.0.0.1 \
  node .next-staging/standalone/server.js
