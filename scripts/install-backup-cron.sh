#!/usr/bin/env bash
#
# Install (or refresh) the nightly Qonvo backup in this user's crontab.
#
# Idempotent: it rewrites its own marked block rather than appending, so running
# it twice does not schedule two backups.
#
#   ./scripts/install-backup-cron.sh            # install at 03:15
#   ./scripts/install-backup-cron.sh --remove   # take it out again
#   ./scripts/install-backup-cron.sh --show     # what is scheduled now
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKER="# qonvo-backup"
LOG_DIR="${HOME}/.local/state/qonvo"
LOG_FILE="${LOG_DIR}/backup.log"
SCHEDULE="${BACKUP_CRON_SCHEDULE:-15 3 * * *}"

# Written to the user crontab, not /etc/cron.d, so it needs no root and the
# backup runs as the user who owns the docker socket access.
LINE="${SCHEDULE} cd ${REPO_DIR} && BACKUP_TARGET_DIR=${HOME}/qonvo-backups ./scripts/backup.sh >> ${LOG_FILE} 2>&1 ${MARKER}"

current() { crontab -l 2>/dev/null || true; }

# grep exits 1 when it matches nothing, which for an empty crontab is the normal
# case, not an error — so every use of it here has to tolerate that.
without_ours() { current | grep -vF "${MARKER}" || true; }

case "${1:-install}" in
  --show)
    current | grep -F "${MARKER}" || echo "(no qonvo backup scheduled)"
    exit 0
    ;;
  --remove)
    without_ours | crontab -
    echo "✓ removed the qonvo backup from crontab"
    exit 0
    ;;
esac

if ! pgrep -x cron >/dev/null 2>&1; then
  echo "WARNING: cron is not running, so this entry will never fire." >&2
  echo "  On WSL, enable systemd in /etc/wsl.conf then: sudo service cron start" >&2
fi

mkdir -p "${LOG_DIR}" "${HOME}/qonvo-backups"

# Drop any previous qonvo line, then add the current one.
{ without_ours; echo "${LINE}"; } | crontab -

echo "✓ nightly backup scheduled"
echo "  when:   ${SCHEDULE}  (crontab -l to confirm)"
echo "  target: ${HOME}/qonvo-backups   (7 dated copies kept, message store excluded)"
echo "  log:    ${LOG_FILE}"
echo
echo "Run it once now to check it works:"
echo "  BACKUP_TARGET_DIR=${HOME}/qonvo-backups ${REPO_DIR}/scripts/backup.sh"
