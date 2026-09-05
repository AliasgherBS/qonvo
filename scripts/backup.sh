#!/usr/bin/env bash
#
# Qonvo nightly backup (DESIGN.md §12.2).
# Backs up Postgres, the WAHA session volume, and the MinIO media bucket to a
# configurable target directory, mirrors MinIO to an offsite bucket if set, and
# prunes local backups older than the retention window.
#
# Requires: docker (compose v2). MinIO offsite mirror additionally needs `mc`.
#
# Crontab example (run nightly at 03:15, log to a file):
#   15 3 * * * cd /opt/qonvo && ./scripts/backup.sh >> /var/log/qonvo-backup.log 2>&1
# Install that line on this box with:  ./scripts/install-backup-cron.sh
#
set -euo pipefail

# --- Config (override via environment or .env) ------------------------------ #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Read the few values we need out of .env WITHOUT sourcing it. `source` treats
# the file as shell, so any value containing shell metacharacters is a syntax
# error that kills the backup — QONVO_EMAIL_FROM="Qonvo <you@example.com>" did
# exactly that (the bare `<` is a redirect). Docker's env_file parser is not a
# shell and never had the problem, so the breakage was invisible until the
# backup was actually run.
env_value() {
	local key="$1" file="${REPO_DIR}/.env"
	[[ -f "$file" ]] || return 0
	# Last assignment wins, matching how docker reads env files.
	sed -n "s/^${key}=//p" "$file" | tail -1 | sed -e 's/^"//' -e 's/"$//'
}

BACKUP_TARGET_DIR="${BACKUP_TARGET_DIR:-$(env_value BACKUP_TARGET_DIR)}"
BACKUP_TARGET_DIR="${BACKUP_TARGET_DIR:-/var/backups/qonvo}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
# Hard cap on how many dated copies are kept, whatever their age. Retention by
# date alone cannot bound disk if the job ever runs more than once a day.
BACKUP_MAX_COPIES="${BACKUP_MAX_COPIES:-7}"
BACKUP_MINIO_TARGET="${BACKUP_MINIO_TARGET:-}" # e.g. "offsite/qonvo-backups" (an mc path)
COMPOSE_PROJECT="${COMPOSE_PROJECT:-qonvo}"

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-qonvo}"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
POSTGRES_DB="${POSTGRES_DB:-qonvo}"
MINIO_BUCKET="${QONVO_MINIO_BUCKET:-$(env_value QONVO_MINIO_BUCKET)}"
MINIO_BUCKET="${MINIO_BUCKET:-qonvo-media}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-$(env_value MINIO_ROOT_USER)}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-qonvo}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(env_value MINIO_ROOT_PASSWORD)}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEST="${BACKUP_TARGET_DIR}/${TIMESTAMP}"
mkdir -p "${DEST}"

echo "[backup] starting → ${DEST}"

compose() { docker compose -p "${COMPOSE_PROJECT}" "$@"; }

# --- 1. Postgres dump (custom format, compressed) --------------------------- #
echo "[backup] pg_dump ${POSTGRES_DB}"
compose exec -T postgres \
	pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc \
	>"${DEST}/postgres_${POSTGRES_DB}.dump"

# --- 2. WAHA session credentials -------------------------------------------- #
# Only the authentication material, NOT the message store. What must survive is
# what saves a tenant from re-scanning their QR: creds.json, the key files and
# app-state. `store.sqlite3` is a cache of the number's entire WhatsApp history
# (measured: 27 MB for a single test number, 93% of it messages) that nothing in
# Qonvo ever reads — conversation context lives in Postgres. Archiving it nightly
# and keeping a week of copies multiplied it by seven for no recovery value.
echo "[backup] WAHA session credentials (excluding the message store)"
WAHA_VOLUME="${COMPOSE_PROJECT}_waha_sessions"
docker run --rm \
	-v "${WAHA_VOLUME}:/data:ro" \
	-v "${DEST}:/backup" \
	alpine:3 \
	tar czf "/backup/waha_sessions.tar.gz" \
	--exclude='store.sqlite3' \
	--exclude='store.sqlite3-wal' \
	--exclude='store.sqlite3-shm' \
	-C /data .

# --- 3. MinIO media bucket (local snapshot) --------------------------------- #
echo "[backup] MinIO bucket ${MINIO_BUCKET}"
MINIO_VOLUME="${COMPOSE_PROJECT}_minio_data"
docker run --rm \
	-v "${MINIO_VOLUME}:/data:ro" \
	-v "${DEST}:/backup" \
	alpine:3 \
	tar czf "/backup/minio_data.tar.gz" -C /data .

# --- 4. Offsite MinIO mirror (optional, needs `mc`) ------------------------- #
if [[ -n "${BACKUP_MINIO_TARGET}" ]]; then
	if command -v mc >/dev/null 2>&1; then
		echo "[backup] mirroring MinIO → ${BACKUP_MINIO_TARGET}"
		mc alias set qonvo-src "http://127.0.0.1:9000" \
			"${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" >/dev/null
		mc mirror --overwrite --remove "qonvo-src/${MINIO_BUCKET}" "${BACKUP_MINIO_TARGET}"
	else
		echo "[backup] WARN: BACKUP_MINIO_TARGET set but 'mc' not installed — skipping offsite mirror"
	fi
fi

# --- 5. Retention pruning --------------------------------------------------- #
echo "[backup] pruning backups older than ${BACKUP_RETENTION_DAYS} days"
find "${BACKUP_TARGET_DIR}" -mindepth 1 -maxdepth 1 -type d \
	-mtime "+${BACKUP_RETENTION_DAYS}" -exec rm -rf {} +

# Then enforce the copy cap, oldest first. Belt to the date-based braces: a job
# that runs twice in a day cannot accumulate past this.
mapfile -t copies < <(find "${BACKUP_TARGET_DIR}" -mindepth 1 -maxdepth 1 -type d | sort)
if (( ${#copies[@]} > BACKUP_MAX_COPIES )); then
	excess=$(( ${#copies[@]} - BACKUP_MAX_COPIES ))
	echo "[backup] pruning ${excess} copy(ies) over the ${BACKUP_MAX_COPIES}-copy cap"
	for ((i = 0; i < excess; i++)); do rm -rf "${copies[i]}"; done
fi

# --- 6. Report what this cost ----------------------------------------------- #
# Printed so the cron log answers "is this eating the disk?" without asking.
this_run=$(du -sh "${DEST}" | cut -f1)
all_runs=$(du -sh "${BACKUP_TARGET_DIR}" | cut -f1)
echo "[backup] this run ${this_run}, all retained copies ${all_runs}"
echo "[backup] done → ${DEST}"
