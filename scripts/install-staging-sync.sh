#!/bin/bash
# Install the timer that keeps staging in step with the working tree.
#
# Idempotent: re-run it after changing either unit file.
set -euo pipefail

UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
cp ~/qonvo/scripts/systemd/qonvo-staging-sync.service "$UNITS/"
cp ~/qonvo/scripts/systemd/qonvo-staging-sync.timer "$UNITS/"

systemctl --user daemon-reload
systemctl --user enable --now qonvo-staging-sync.timer

echo
systemctl --user list-timers qonvo-staging-sync.timer --no-pager
echo
echo "Logs: /tmp/qonvo-staging-sync.log"
echo "Force a rebuild now: ~/qonvo/scripts/staging-sync.sh --force"
