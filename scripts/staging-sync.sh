#!/bin/bash
# Rebuild staging if, and only if, the dashboard sources have changed.
#
# Staging serves this machine's working tree, so it goes stale the moment
# anything changes it: a branch switch, a merge, an edit. Nothing noticed, so
# dev.qonvo.org served whatever was built last -- once a build from a branch
# that predated the feature somebody was trying to look at, which reads as "my
# change did not deploy" rather than "nobody rebuilt".
#
# Run by qonvo-staging-sync.timer every minute. Cheap when nothing has changed:
# one find over the dashboard sources and a hash.
#
#   ./scripts/staging-sync.sh          rebuild if stale
#   ./scripts/staging-sync.sh --force  rebuild regardless
set -euo pipefail

REPO="$HOME/qonvo"
STATE="$HOME/.cache/qonvo-staging"
mkdir -p "$STATE"

SEEN="$STATE/fingerprint-seen"
BUILT="$STATE/fingerprint-built"
LOG="/tmp/qonvo-staging-sync.log"

log() { echo "$(date -Is) $*" >>"$LOG"; }

# Size and mtime of everything that can change the built output, which is the
# sources plus the env file -- NEXT_PUBLIC_* is baked in at build time, so an
# edit there changes the bundle without touching a single .tsx.
#
# Content hashing would be stricter and much slower. Size and mtime is what
# every build tool uses for the same decision, and the cost of being wrong here
# is one unnecessary rebuild.
fingerprint() {
  {
    find "$REPO/dashboard" \
      \( -name node_modules -o -name '.next*' \) -prune -o \
      -type f -printf '%T@ %s %p\n'
    # The branch, so a checkout that restores identical mtimes still counts.
    git -C "$REPO" rev-parse HEAD 2>/dev/null || true
  } | sort | sha256sum | cut -d' ' -f1
}

now="$(fingerprint)"

# Used by run-dashboard-staging.sh --build: somebody just built by hand, so
# record that state as current and do not build it again a minute later.
if [[ "${1:-}" == "--fingerprint-only" ]]; then
  echo "$now" >"$SEEN"
  echo "$now" >"$BUILT"
  exit 0
fi

built="$(cat "$BUILT" 2>/dev/null || echo none)"
seen="$(cat "$SEEN" 2>/dev/null || echo none)"
echo "$now" >"$SEEN"

if [[ "${1:-}" != "--force" ]]; then
  if [[ "$now" == "$built" ]]; then
    exit 0
  fi
  # Changed since the last tick as well as since the last build, which means
  # somebody is still typing. Waiting one tick keeps a build from starting in
  # the middle of a series of saves, and costs at most a minute of staleness.
  if [[ "$now" != "$seen" ]]; then
    log "changed, waiting one tick to settle"
    exit 0
  fi
fi

log "rebuilding staging"
if ! "$REPO/scripts/staging-build.sh" >>"$LOG" 2>&1; then
  # Deliberately does NOT record the fingerprint, so the next tick tries again.
  # The running server is untouched: a failed build must leave staging serving
  # the last thing that worked rather than nothing at all.
  log "BUILD FAILED - staging still serving the previous build"
  exit 1
fi

systemctl --user restart qonvo-dashboard-staging
echo "$now" >"$BUILT"
log "rebuilt and restarted"
