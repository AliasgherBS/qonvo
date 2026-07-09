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
#
set -euo pipefail

# --- Config (override via environment or .env) ------------------------------ #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load .env if present (for POSTGRES_* / BACKUP_* / MinIO creds).
if [[ -f "${REPO_DIR}/.env" ]]; then
	set -a
	# shellcheck disable=SC1091
	source "${REPO_DIR}/.env"
	set +a
fi

BACKUP_TARGET_DIR="${BACKUP_TARGET_DIR:-/var/backups/qonvo}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_MINIO_TARGET="${BACKUP_MINIO_TARGET:-}" # e.g. "offsite/qonvo-backups" (an mc path)
COMPOSE_PROJECT="${COMPOSE_PROJECT:-qonvo}"

POSTGRES_USER="${POSTGRES_USER:-qonvo}"
POSTGRES_DB="${POSTGRES_DB:-qonvo}"
MINIO_BUCKET="${QONVO_MINIO_BUCKET:-qonvo-media}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-qonvo}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-}"

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

# --- 2. WAHA session volume tarball ----------------------------------------- #
# Losing this volume = every tenant re-scans their QR (accepted worst case).
echo "[backup] WAHA session volume"
WAHA_VOLUME="${COMPOSE_PROJECT}_waha_sessions"
docker run --rm \
	-v "${WAHA_VOLUME}:/data:ro" \
	-v "${DEST}:/backup" \
	alpine:3 \
	tar czf "/backup/waha_sessions.tar.gz" -C /data .

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

echo "[backup] done → ${DEST}"
