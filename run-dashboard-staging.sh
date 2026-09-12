#!/bin/bash
# Serve the staging dashboard: host node process on 3012, pointed at the
# staging API. This is what qonvo-dashboard-staging.service runs.
#
# It SERVES. It does not build. Building lives in scripts/staging-build.sh and
# happens automatically through scripts/staging-sync.sh, run by
# qonvo-staging-sync.timer.
#
# That split is deliberate and it is load-bearing. This script used to take
# --build and then exec the server, so running it by hand while the systemd
# unit was up started a second server competing for port 3012. Whichever lost
# kept serving whatever build it had started with, and the symptom was a change
# that would not appear no matter how many times you rebuilt.
#
#   ./run-dashboard-staging.sh          serve (what systemd runs)
#   ./run-dashboard-staging.sh --build  build, then restart the service
#
# --build is kept because it is in muscle memory and in the docs, but it no
# longer serves anything itself: it builds, restarts the unit, and exits.
set -euo pipefail

if [[ "${1:-}" == "--build" || "${1:-}" == "--build-only" ]]; then
  ~/qonvo/scripts/staging-build.sh
  systemctl --user restart qonvo-dashboard-staging
  # Record it, so the sync timer does not immediately rebuild what was just
  # built by hand.
  mkdir -p ~/.cache/qonvo-staging
  ~/qonvo/scripts/staging-sync.sh --fingerprint-only 2>/dev/null || true
  echo "Staging rebuilt and restarted."
  exit 0
fi

cd ~/qonvo/dashboard
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

ENV_FILE=".env.staging.local"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing dashboard/$ENV_FILE - copy $ENV_FILE.example and fill it in." >&2
  exit 1
fi

if [[ ! -f .next-staging/standalone/server.js ]]; then
  echo "No staging build yet - run: ./scripts/staging-build.sh" >&2
  exit 1
fi

# NEXT_DIST_DIR is needed at *serve* time as well as at build time.
# next.config.ts reads it to set distDir, and the standalone server resolves
# /_next/static against that -- so without it the server looks in .next/static,
# finds nothing, and answers 400 to every chunk. The page renders its HTML and
# then loads no JavaScript at all, which looks like a broken build rather than
# a missing variable. Found by pointing a browser at it.
# shellcheck disable=SC2046
exec env $(grep -v '^#' "$ENV_FILE" | xargs) \
  NEXT_DIST_DIR=.next-staging \
  PORT=3012 HOSTNAME=127.0.0.1 \
  node .next-staging/standalone/server.js
