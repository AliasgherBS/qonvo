#!/bin/bash
# Build the staging dashboard. Builds only -- it never starts a server.
#
# That separation is the whole point of this file existing. Building and
# serving used to be one script, and `--build` finished by exec'ing the server,
# so running it from a terminal while the systemd unit was up started a SECOND
# server competing for port 3012. Whichever lost kept serving whatever build it
# had started with, and the symptom was a change that would not appear no
# matter how many times you rebuilt. That cost a day once, and then cost
# another session an hour.
#
#   ./scripts/staging-build.sh && systemctl --user restart qonvo-dashboard-staging
#
# Builds into .next-staging via a distinct distDir, so a staging build and a
# production build can coexist: both bake NEXT_PUBLIC_* in at build time, so
# sharing one .next directory would mean whichever built last wins and the
# other silently serves the wrong API URL and the wrong environment badge.
set -euo pipefail

cd ~/qonvo/dashboard
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

ENV_FILE=".env.staging.local"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing dashboard/$ENV_FILE - copy $ENV_FILE.example and fill it in." >&2
  exit 1
fi

# NEXT_DIST_DIR is read by next.config.ts; the env file supplies the
# NEXT_PUBLIC_* values that get baked into this build.
# shellcheck disable=SC2046
env $(grep -v '^#' "$ENV_FILE" | xargs) NEXT_DIST_DIR=.next-staging npm run build

# Standalone needs static assets and public/ copied in beside it. Removing them
# first is required: stale chunks cause ChunkLoadError in the browser.
rm -rf .next-staging/standalone/.next-staging/static .next-staging/standalone/public
mkdir -p .next-staging/standalone/.next-staging
cp -r public .next-staging/standalone/
cp -r .next-staging/static .next-staging/standalone/.next-staging/
