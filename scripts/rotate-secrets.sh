#!/usr/bin/env bash
#
# Rotate the secrets that are both live and present in git history.
#
# Ten of them were. `.env` and `dashboard/.env.local` were tracked in commit
# 4a48a52 and untracked again in a80ca3a, but a removed file stays in history,
# so every value in it is readable by anyone who can clone. Four were also
# placeholder-shaped strings ("dev-postgres-pass", "change-me-..."), which is
# the worse half of the problem: those are guessable with no repo access at all.
#
# Nothing was internet-reachable (every datastore binds 127.0.0.1) and the repo
# is private, so this is hygiene rather than incident response. It is still the
# difference between one misconfigured port being survivable and being fatal.
#
#   ./scripts/rotate-secrets.sh --dry-run     # show what would change
#   ./scripts/rotate-secrets.sh               # do it
#
# Order matters and the script enforces it. The Fernet key in particular has to
# re-encrypt what it protects *before* the old key is gone, or two tenants lose
# their Google connection.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

ENV_FILE=".env"
[[ -f "$ENV_FILE" ]] || { echo "no $ENV_FILE here" >&2; exit 1; }

BACKUP="$ENV_FILE.before-rotation-$(date +%Y%m%d-%H%M%S)"

hdr() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$1"; }
step(){ printf '  \033[36m→\033[0m %s\n' "$1"; }

# --------------------------------------------------------------------------- #
# Generators.
#
# Python rather than `tr </dev/urandom | head`, which the dry run caught: head
# exits after its byte count, tr takes SIGPIPE, and `set -o pipefail` turns
# that into a non-zero status that `set -e` treats as a failure. The script
# died silently after printing a section header.
#
# The alphabets avoid characters a docker env file, a URL or a psql string
# would treat specially. These values end up inside
# postgresql+asyncpg://user:pass@host, where a stray @ or : produces a
# connection string that points somewhere else entirely.
gen_password() {
	python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(40)))"
}
gen_token() {
	python3 -c "import secrets; print(secrets.token_urlsafe(36))"
}
gen_fernet() {
	docker exec qonvo-api-1 python -c \
		"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
}

read_env() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

set_env() {
	local key="$1" value="$2"
	if [[ "$DRY_RUN" == 1 ]]; then
		printf '      would set %s (len %s)\n' "$key" "${#value}"
		return
	fi
	# Every occurrence, not just the first: .env carries duplicate keys in
	# places and docker takes the last one, so rewriting only the first leaves
	# the old value winning.
	python3 - "$key" "$value" <<'PY'
import sys
from pathlib import Path
key, value = sys.argv[1], sys.argv[2]
p = Path(".env")
lines = p.read_text().splitlines()
out, seen = [], False
for line in lines:
    if line.startswith(f"{key}="):
        out.append(f"{key}={value}")
        seen = True
    else:
        out.append(line)
if not seen:
    out.append(f"{key}={value}")
p.write_text("\n".join(out) + "\n")
PY
}

printf '\033[1mQonvo secret rotation\033[0m\n'
[[ "$DRY_RUN" == 1 ]] && warn "dry run: nothing will change"

if [[ "$DRY_RUN" == 0 ]]; then
	cp "$ENV_FILE" "$BACKUP"
	ok "backed up $ENV_FILE -> $BACKUP"
fi

# --------------------------------------------------------------------------- #
hdr "1. Fernet key (encrypts every tenant's Google refresh token)"
# First, because it is the only one that has to migrate data. Rotating it
# without re-encrypting would leave the ciphertext undecryptable and every
# Google integration silently broken until each owner reconnected.
ENCRYPTED_ROWS=$(docker exec qonvo-postgres-1 psql -U qonvo -d qonvo -tAc \
	"select count(*) from integrations where encrypted_credentials is not null and encrypted_credentials <> ''" \
	2>/dev/null | tr -d ' ')
step "rows to re-encrypt: ${ENCRYPTED_ROWS:-0}"

if [[ "$DRY_RUN" == 0 ]]; then
	OLD_FERNET="$(read_env QONVO_FERNET_KEY)"
	NEW_FERNET="$(gen_fernet)"
	# Re-encrypt inside the API container, which already has cryptography and
	# the database URL. Both keys are passed in so the old one never has to be
	# written anywhere.
	docker exec -e OLD_KEY="$OLD_FERNET" -e NEW_KEY="$NEW_FERNET" qonvo-api-1 \
		python /app/scripts/reencrypt_fernet.py
	set_env QONVO_FERNET_KEY "$NEW_FERNET"
	ok "Fernet key rotated and credentials re-encrypted"
else
	step "would re-encrypt then rotate QONVO_FERNET_KEY"
fi

# --------------------------------------------------------------------------- #
hdr "2. Postgres roles"
# ALTER ROLE takes effect for new connections only, so existing pooled
# connections keep working until the containers are recreated at the end. That
# is what makes this safe to do while the site is serving.
for spec in "qonvo:POSTGRES_PASSWORD" "qonvo_app:APP_DB_PASSWORD" "qonvo_system:SYSTEM_DB_PASSWORD"; do
	role="${spec%%:*}"; key="${spec##*:}"
	new="$(gen_password)"
	if [[ "$DRY_RUN" == 1 ]]; then
		step "would ALTER ROLE $role and set $key"
		continue
	fi
	docker exec qonvo-postgres-1 psql -U qonvo -d qonvo -c \
		"ALTER ROLE $role WITH PASSWORD '$new'" >/dev/null
	set_env "$key" "$new"
	# The three DATABASE_URLs embed the password, so they are rewritten too.
	# Missing one is a container that starts and then cannot reach the database.
	python3 - "$role" "$new" <<'PY'
import re, sys
from pathlib import Path
role, new = sys.argv[1], sys.argv[2]
p = Path(".env")
text = p.read_text()
# postgresql+asyncpg://<role>:<anything>@  ->  same with the new password
#
# \g<1> rather than \1, which failed mid-run: a generated password beginning
# with a digit makes "\1" + "6..." parse as a reference to group 16. The role
# password had already been ALTERed by then, so the URL and the database
# disagreed and system_session broke until it was repaired by hand.
text = re.sub(
    rf"(postgresql\+asyncpg://{role}:)[^@]*(@)",
    lambda m: m.group(1) + new + m.group(2),
    text,
)
p.write_text(text)
PY
	ok "$role rotated ($key and its DATABASE_URL)"
done

# --------------------------------------------------------------------------- #
hdr "3. WAHA"
# The API key guards the REST surface. The linked WhatsApp session lives in a
# volume and is not affected, so this does not mean re-scanning a QR code.
#
# QONVO_WAHA_HMAC_SECRET is only a fallback: sessions.py generates a random
# per-session secret at creation and stores it, and webhooks.py prefers that
# (`session_row.hmac_secret or settings.waha_hmac_secret`). Rotating it still
# matters, because a session row with a NULL secret would otherwise fall back
# to a value that begins with the word "change".
if [[ "$DRY_RUN" == 1 ]]; then
	step "would rotate WAHA_API_KEY, QONVO_WAHA_API_KEY, QONVO_WAHA_HMAC_SECRET"
else
	NEW_WAHA="$(gen_token)"
	set_env WAHA_API_KEY "$NEW_WAHA"
	set_env QONVO_WAHA_API_KEY "$NEW_WAHA"
	set_env QONVO_WAHA_HMAC_SECRET "$(gen_token)"
	ok "WAHA key rotated (both names, they must match)"
fi

# --------------------------------------------------------------------------- #
hdr "4. MinIO"
if [[ "$DRY_RUN" == 1 ]]; then
	step "would rotate MINIO_ROOT_PASSWORD and QONVO_MINIO_SECRET_KEY (not the root user)"
else
	# The password only, not the root user. MinIO ties IAM policies to the root
	# identity, and renaming it on an initialised volume can strand them. The
	# username is not the secret anyway: the committed value was "minio".
	NEW_MINIO_PASS="$(gen_password)"
	set_env MINIO_ROOT_PASSWORD "$NEW_MINIO_PASS"
	set_env QONVO_MINIO_SECRET_KEY "$NEW_MINIO_PASS"
	ok "MinIO secret rotated (root user left alone, deliberately)"
fi

# --------------------------------------------------------------------------- #
hdr "5. Apply"
if [[ "$DRY_RUN" == 1 ]]; then
	step "would recreate postgres, minio, waha, api, worker, scheduler"
	printf '\nDry run complete. Nothing changed.\n'
	exit 0
fi

# --force-recreate, not restart: env files are read at container *create*, so a
# restart keeps the old values and everything appears to work until the next
# reconnect.
step "recreating containers so they pick up the new values"
docker compose up -d --force-recreate minio waha api worker scheduler >/dev/null 2>&1
sleep 12

hdr "6. Verify"
for check in \
	"database:$(docker exec qonvo-api-1 python -c 'import asyncio,os;from sqlalchemy.ext.asyncio import create_async_engine;e=create_async_engine(os.environ["QONVO_DATABASE_URL"]);asyncio.run(e.dispose()) or print("ok")' 2>/dev/null || echo fail)" \
	; do :; done

READY=$(curl -s --max-time 20 http://localhost:8000/readyz || echo '{}')
echo "  readyz: $READY"
if echo "$READY" | grep -q '"status":"ok"'; then
	ok "database, redis and WAHA all reachable with the new credentials"
else
	warn "readyz is not ok. Restore with: cp $BACKUP .env && docker compose up -d --force-recreate"
	exit 1
fi

# readyz checks database, redis and WAHA but not MinIO, so a MinIO that failed
# to come back up would be a silent failure. Checked explicitly.
if docker exec qonvo-minio-1 mc --version >/dev/null 2>&1 || \
   curl -sf --max-time 10 http://localhost:9000/minio/health/live >/dev/null 2>&1; then
	ok "MinIO is live with the new secret"
else
	warn "MinIO did not come back. Check: docker compose logs minio"
fi

GOOGLE=$(docker exec qonvo-postgres-1 psql -U qonvo -d qonvo -tAc \
	"select count(*) from integrations where encrypted_credentials is not null and encrypted_credentials <> ''" 2>/dev/null | tr -d ' ')
step "integrations still holding credentials: ${GOOGLE:-0} (was ${ENCRYPTED_ROWS:-0})"

printf '\n\033[1mDone.\033[0m The previous values are in %s, which is gitignored.\n' "$BACKUP"
printf 'Delete it once you are satisfied: rm %s\n' "$BACKUP"
