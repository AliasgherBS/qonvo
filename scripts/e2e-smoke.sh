#!/usr/bin/env bash
#
# Qonvo automated end-to-end smoke test.
#
# Covers everything that can be checked WITHOUT a phone, a Google account or a
# mailbox: auth and authorisation, every read endpoint, the billing lifecycle,
# knowledge ingestion, and the inbound message pipeline driven by synthetic
# HMAC-signed webhooks (which is how gates, dedupe and rate limiting get
# exercised with no WhatsApp involved).
#
# What it deliberately cannot cover is in docs/E2E-LIVE-TEST-PLAN.md part 2.
#
#   ./scripts/e2e-smoke.sh                 # staging (default, and the safe one)
#   ./scripts/e2e-smoke.sh --env production --allow-production
#   ./scripts/e2e-smoke.sh --keep          # leave test data behind for poking at
#
# Defaults to staging on purpose: this creates and deletes real rows.
set -uo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENV_NAME="staging"
ALLOW_PROD=0
KEEP=0
while [[ $# -gt 0 ]]; do
	case "$1" in
	--env) ENV_NAME="$2"; shift 2 ;;
	--allow-production) ALLOW_PROD=1; shift ;;
	--keep) KEEP=1; shift ;;
	-h | --help) sed -n '3,20p' "$0"; exit 0 ;;
	*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
done

case "$ENV_NAME" in
staging)
	API="http://localhost:8010"
	PG_CONTAINER="qonvo-staging-postgres-1"
	WAHA_URL="http://localhost:3011"
	ENV_FILE_FOR_WAHA=".env.staging"
	;;
production)
	API="http://localhost:8000"
	PG_CONTAINER="qonvo-postgres-1"
	WAHA_URL="http://localhost:3001"
	ENV_FILE_FOR_WAHA=".env"
	if [[ "$ALLOW_PROD" -ne 1 ]]; then
		echo "Refusing to write test data to production." >&2
		echo "Run against staging, or pass --allow-production if you mean it." >&2
		exit 1
	fi
	;;
*) echo "--env must be staging or production" >&2; exit 2 ;;
esac

OWNER_EMAIL="${QONVO_E2E_OWNER_EMAIL:-owner@dev.dev}"
OWNER_PASSWORD="${QONVO_E2E_OWNER_PASSWORD:-dev-password-123}"
ADMIN_EMAIL="${QONVO_E2E_ADMIN_EMAIL:-admin@qonvo.dev}"
ADMIN_PASSWORD="${QONVO_E2E_ADMIN_PASSWORD:-dev-admin-123}"

PASS=0
FAIL=0
SKIP=0
FAILED_NAMES=()

green() { printf '\033[32m%s\033[0m' "$1"; }
red() { printf '\033[31m%s\033[0m' "$1"; }
yellow() { printf '\033[33m%s\033[0m' "$1"; }

ok() { PASS=$((PASS + 1)); printf '  %s %s\n' "$(green PASS)" "$1"; }
no() {
	FAIL=$((FAIL + 1))
	FAILED_NAMES+=("$1")
	printf '  %s %s\n' "$(red FAIL)" "$1"
	[[ -n "${2:-}" ]] && printf '         %s\n' "$2"
}
skip() { SKIP=$((SKIP + 1)); printf '  %s %s  (%s)\n' "$(yellow SKIP)" "$1" "${2:-}"; }
phase() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# expect_code <name> <expected> <curl args...>
expect_code() {
	local name="$1" want="$2"; shift 2
	local got
	got=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@")
	if [[ "$got" == "$want" ]]; then ok "$name"; else no "$name" "expected HTTP $want, got $got"; fi
}

jqp() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null; }

psql_q() { docker exec "$PG_CONTAINER" psql -U qonvo -d qonvo -tAc "$1" 2>/dev/null | tr -d ' '; }

printf '\033[1mQonvo e2e smoke — %s (%s)\033[0m\n' "$ENV_NAME" "$API"

# --------------------------------------------------------------------------- #
phase "1. Infrastructure"
# --------------------------------------------------------------------------- #
expect_code "/healthz is 200" 200 "$API/healthz"

ready=$(curl -s --max-time 20 "$API/readyz")
if [[ "$(echo "$ready" | jqp "d['status']")" == "ok" ]]; then
	ok "/readyz reports every dependency healthy"
else
	no "/readyz reports every dependency healthy" "$ready"
fi

metrics=$(curl -s --max-time 20 "$API/metrics")
if grep -q "qonvo_" <<<"$metrics"; then
	ok "/metrics renders business metrics"
else
	no "/metrics renders business metrics" "no qonvo_ series found"
fi

# --------------------------------------------------------------------------- #
phase "2. Authentication and authorisation"
# --------------------------------------------------------------------------- #
login() {
	curl -s --max-time 20 -X POST "$API/api/auth/login" \
		-H 'Content-Type: application/json' \
		-d "{\"email\":\"$1\",\"password\":\"$2\"}"
}

OWNER_TOKEN=$(login "$OWNER_EMAIL" "$OWNER_PASSWORD" | jqp "d.get('access_token','')")
if [[ -n "$OWNER_TOKEN" ]]; then ok "owner can sign in"; else
	no "owner can sign in" "no token for $OWNER_EMAIL — is this environment seeded?"
	echo; echo "Cannot continue without an owner session. Run: ./qonvo-staging.sh seed"; exit 1
fi
OH=(-H "Authorization: Bearer $OWNER_TOKEN")

ADMIN_TOKEN=$(login "$ADMIN_EMAIL" "$ADMIN_PASSWORD" | jqp "d.get('access_token','')")
if [[ -n "$ADMIN_TOKEN" ]]; then ok "platform admin can sign in"; else
	skip "platform admin can sign in" "password rotated? set QONVO_E2E_ADMIN_PASSWORD"
fi
AH=(-H "Authorization: Bearer ${ADMIN_TOKEN:-none}")

expect_code "a wrong password is rejected" 401 -X POST "$API/api/auth/login" \
	-H 'Content-Type: application/json' \
	-d "{\"email\":\"$OWNER_EMAIL\",\"password\":\"definitely-not-it\"}"

expect_code "an unauthenticated request is rejected" 401 "$API/api/billing"
expect_code "an owner cannot reach admin routes" 403 "$API/api/admin/tenants" "${OH[@]}"
if [[ -n "${ADMIN_TOKEN:-}" ]]; then
	expect_code "an admin can reach admin routes" 200 "$API/api/admin/tenants" "${AH[@]}"
fi

TENANT_ID=$(curl -s --max-time 20 "$API/api/me" "${OH[@]}" | jqp "d.get('tenant_id','')")
[[ -n "$TENANT_ID" ]] && ok "/api/me identifies the tenant" || no "/api/me identifies the tenant"

# --------------------------------------------------------------------------- #
phase "3. Every owner read endpoint answers"
# --------------------------------------------------------------------------- #
for ep in /api/me /api/billing /api/billing/plans /api/onboarding /api/config \
	/api/conversations /api/knowledge/sources /api/knowledge/gaps /api/sessions \
	/api/integrations /api/analytics/summary /api/notifications /api/team \
	/api/account/export; do
	expect_code "GET $ep" 200 "$API$ep" "${OH[@]}"
done

# --------------------------------------------------------------------------- #
phase "4. Billing lifecycle"
# --------------------------------------------------------------------------- #
plans=$(curl -s --max-time 20 "$API/api/billing/plans" "${OH[@]}")
if [[ "$(echo "$plans" | jqp "[p['key'] for p in d]" | tr -d "[]' ")" == "trial,starter,growth,scale" ]]; then
	ok "the plan catalogue lists four plans in upgrade order"
else
	no "the plan catalogue lists four plans in upgrade order" "$plans"
fi
if grep -qi "price\|\\$\|PKR" <<<"$plans"; then
	no "no prices leak through the API" "a price-like field appeared in /api/billing/plans"
else
	ok "no prices leak through the API"
fi

checkout=$(curl -s --max-time 20 -X POST "$API/api/billing/checkout" "${OH[@]}" \
	-H 'Content-Type: application/json' -d '{"plan_key":"growth"}')
if [[ -n "$(echo "$checkout" | jqp "d.get('instructions') or ''")" ]]; then
	ok "checkout with no gateway returns instructions, not an error"
else
	no "checkout with no gateway returns instructions, not an error" "$checkout"
fi

expect_code "checkout refuses an unknown plan" 400 -X POST "$API/api/billing/checkout" \
	"${OH[@]}" -H 'Content-Type: application/json' -d '{"plan_key":"unlimited"}'
expect_code "checkout refuses the trial plan" 400 -X POST "$API/api/billing/checkout" \
	"${OH[@]}" -H 'Content-Type: application/json' -d '{"plan_key":"trial"}'

if [[ -n "${ADMIN_TOKEN:-}" ]]; then
	# Remember what to put back, so this is safe to run repeatedly.
	BEFORE_PLAN=$(psql_q "select plan from tenants where id='$TENANT_ID'")
	BEFORE_ENT=$(psql_q "select coalesce(entitlements::text,'{}') from tenant_config where tenant_id='$TENANT_ID'")
	HAD_SUB=$(psql_q "select count(*) from subscriptions where tenant_id='$TENANT_ID'")

	curl -s -o /dev/null --max-time 20 -X PUT "$API/api/admin/tenants/$TENANT_ID/subscription" \
		"${AH[@]}" -H 'Content-Type: application/json' \
		-d '{"plan_key":"scale","status":"active"}'
	b=$(curl -s --max-time 20 "$API/api/billing" "${OH[@]}")
	if [[ "$(echo "$b" | jqp "d['entitlements'].get('monthly_message_quota')")" == "20000" ]]; then
		ok "an admin plan change rewrites entitlements from the catalogue"
	else
		no "an admin plan change rewrites entitlements from the catalogue" "$b"
	fi

	# A cancellation whose period has already ended must block service.
	curl -s -o /dev/null --max-time 20 -X PUT "$API/api/admin/tenants/$TENANT_ID/subscription" \
		"${AH[@]}" -H 'Content-Type: application/json' \
		-d '{"plan_key":"scale","status":"canceled","current_period_end":"2020-01-01T00:00:00Z"}'
	b=$(curl -s --max-time 20 "$API/api/billing" "${OH[@]}")
	if [[ "$(echo "$b" | jqp "d['blocked_reason']")" == "canceled" ]]; then
		ok "an expired cancellation blocks service with the right reason"
	else
		no "an expired cancellation blocks service with the right reason" "$b"
	fi

	# A payment that just failed must NOT block: the grace window exists so a
	# card failing this morning does not silence a business today.
	curl -s -o /dev/null --max-time 20 -X PUT "$API/api/admin/tenants/$TENANT_ID/subscription" \
		"${AH[@]}" -H 'Content-Type: application/json' \
		-d "{\"plan_key\":\"scale\",\"status\":\"past_due\",\"current_period_end\":\"$(date -u -d '1 day ago' +%FT%TZ)\"}"
	b=$(curl -s --max-time 20 "$API/api/billing" "${OH[@]}")
	if [[ "$(echo "$b" | jqp "d['expired']")" == "False" ]]; then
		ok "a just-failed payment keeps answering (grace window)"
	else
		no "a just-failed payment keeps answering (grace window)" "$b"
	fi

	expect_code "an admin plan change refuses an unknown plan" 400 \
		-X PUT "$API/api/admin/tenants/$TENANT_ID/subscription" "${AH[@]}" \
		-H 'Content-Type: application/json' -d '{"plan_key":"bespoke","status":"active"}'

	if [[ "$KEEP" -eq 0 ]]; then
		[[ "$HAD_SUB" == "0" ]] && psql_q "delete from subscriptions where tenant_id='$TENANT_ID'" >/dev/null
		psql_q "update tenant_config set entitlements='${BEFORE_ENT}'::jsonb where tenant_id='$TENANT_ID'" >/dev/null
		psql_q "update tenants set plan='${BEFORE_PLAN}' where id='$TENANT_ID'" >/dev/null
		psql_q "delete from audit_log where tenant_id='$TENANT_ID' and action='tenant.subscription.set'" >/dev/null
		ok "billing state restored to how it was found"
	fi
else
	skip "billing admin lifecycle" "no admin session"
fi

# --------------------------------------------------------------------------- #
phase "5. Knowledge"
# --------------------------------------------------------------------------- #
SRC=$(curl -s --max-time 30 -X POST "$API/api/knowledge/sources" "${OH[@]}" \
	-H 'Content-Type: application/json' \
	-d '{"type":"manual","title":"e2e smoke source","content":"Our smoke-test hours are 9am to 5pm, Monday to Friday. The smoke-test refund window is 14 days."}')
SRC_ID=$(echo "$SRC" | jqp "d.get('id','')")
if [[ -n "$SRC_ID" ]]; then
	ok "a text knowledge source can be created"
	# Ingestion is an async worker job; give it a moment before judging.
	for _ in 1 2 3 4 5 6 7 8 9 10; do
		st=$(curl -s --max-time 20 "$API/api/knowledge/sources/$SRC_ID" "${OH[@]}" | jqp "d.get('status','')")
		[[ "$st" == "ready" ]] && break
		sleep 2
	done
	if [[ "$st" == "ready" ]]; then
		ok "the worker ingested it (status: ready)"
	else
		no "the worker ingested it (status: ready)" "still '$st' after 20s — is the worker running?"
	fi
	chunks=$(psql_q "select count(*) from knowledge_chunks where source_id='$SRC_ID'")
	if [[ "${chunks:-0}" -gt 0 ]]; then
		ok "it produced embedded chunks ($chunks)"
	else
		no "it produced embedded chunks" "0 chunks — check the embedding provider key"
	fi
	if [[ "$KEEP" -eq 0 ]]; then
		expect_code "the source can be deleted" 204 -X DELETE "$API/api/knowledge/sources/$SRC_ID" "${OH[@]}"
	fi
else
	no "a text knowledge source can be created" "$SRC"
fi

# --------------------------------------------------------------------------- #
phase "6. Inbound pipeline (synthetic webhooks, no phone involved)"
# --------------------------------------------------------------------------- #
# The webhook is the whole product's front door. Signing one by hand exercises
# tenant resolution, HMAC verification, the chat-id filter, dedupe and the rate
# limiter without WhatsApp being reachable at all.
SESSION_NAME=$(psql_q "select session_name from whatsapp_sessions where tenant_id='$TENANT_ID' limit 1")
CREATED_SESSION=0
if [[ -z "$SESSION_NAME" ]]; then
	# Create one. An unlinked session messages nobody -- it sits waiting for a
	# QR scan -- but it gives the webhook a tenant to resolve to, which is what
	# this phase needs. Only ever on staging.
	if [[ "$ENV_NAME" == "staging" ]]; then
		mk=$(curl -s --max-time 60 -X POST "$API/api/sessions" "${OH[@]}" \
			-H 'Content-Type: application/json' \
			-d '{"session_name":"e2e-smoke","label":"e2e smoke (unlinked)"}')
		SESSION_NAME=$(echo "$mk" | jqp "d.get('session_name','')")
		if [[ -n "$SESSION_NAME" ]]; then
			CREATED_SESSION=1
			ok "created an unlinked session for the pipeline checks"
		else
			no "created an unlinked session for the pipeline checks" "$mk"
		fi
	fi
fi
if [[ -z "$SESSION_NAME" ]]; then
	skip "inbound pipeline" "no whatsapp_sessions row, and not creating one outside staging"
else
	HMAC_SECRET=$(psql_q "select coalesce(hmac_secret,'') from whatsapp_sessions where session_name='$SESSION_NAME'")

	post_webhook() { # post_webhook <message-id> <chat-id> <body>
		local body payload sig
		# The timestamp must be NOW. A fixed past value is older than the
		# staleness threshold, so the pipeline correctly decides the backlog is
		# stale and sends only a catch-up reply instead of processing the
		# message -- which looks like a pipeline failure but is the gate working.
		payload=$(python3 -c "
import json,sys,time
print(json.dumps({'session': sys.argv[1], 'event': 'message', 'payload': {
    'id': sys.argv[2], 'from': sys.argv[3], 'fromMe': False,
    'body': sys.argv[4], 'timestamp': int(time.time())}}))" \
			"$SESSION_NAME" "$1" "$2" "$3")
		sig=$(python3 -c "
import hmac,hashlib,sys
print(hmac.new(sys.argv[1].encode(), sys.argv[2].encode(), hashlib.sha512).hexdigest())" \
			"$HMAC_SECRET" "$payload")
		curl -s --max-time 20 -X POST "$API/webhooks/waha" \
			-H 'Content-Type: application/json' -H "X-Webhook-Hmac: $sig" -d "$payload"
	}

	# An unsigned delivery must be refused. This is the failure mode that a
	# WAHA global webhook causes, and it 401s every message when it happens.
	expect_code "an unsigned webhook is rejected" 401 -X POST "$API/webhooks/waha" \
		-H 'Content-Type: application/json' \
		-d "{\"session\":\"$SESSION_NAME\",\"event\":\"message\",\"payload\":{\"id\":\"x\",\"from\":\"1@c.us\"}}"

	MSG_ID="e2e-$(date +%s)-1"
	CHAT="923000000001@c.us"
	r=$(post_webhook "$MSG_ID" "$CHAT" "what are your smoke-test hours?")
	if [[ "$(echo "$r" | jqp "d['status']")" == "buffered" ]]; then
		ok "a signed inbound message is accepted and buffered"
	else
		no "a signed inbound message is accepted and buffered" "$r"
	fi

	r=$(post_webhook "$MSG_ID" "$CHAT" "same message again")
	if [[ "$(echo "$r" | jqp "d.get('reason','')")" == "duplicate" ]]; then
		ok "a replayed message id is deduplicated"
	else
		no "a replayed message id is deduplicated" "$r"
	fi

	r=$(post_webhook "e2e-group-$(date +%s)" "1234-5678@g.us" "group chatter")
	if [[ "$(echo "$r" | jqp "d.get('reason','')")" == "non_user_chat" ]]; then
		ok "a group chat is filtered out"
	else
		no "a group chat is filtered out" "$r"
	fi

	# The limiter is 20 per 60s per chat, so 25 must trip it.
	limited=0
	for i in $(seq 1 25); do
		r=$(post_webhook "e2e-flood-$(date +%s)-$i" "923000000002@c.us" "flood $i")
		[[ "$(echo "$r" | jqp "d.get('reason','')")" == "rate_limited" ]] && limited=1
	done
	if [[ "$limited" -eq 1 ]]; then
		ok "a flooding chat gets rate limited"
	else
		no "a flooding chat gets rate limited" "25 rapid messages never tripped the limiter"
	fi

	# The worker has to close the debounce window, then run the pipeline. On an
	# unlinked session the send fails and arq retries, so this can take ~30s.
	# Poll rather than sleeping a guessed interval.
	convs=""
	for _ in $(seq 1 20); do
		convs=$(curl -s --max-time 20 "$API/api/conversations" "${OH[@]}")
		grep -q "923000000001" <<<"$convs" && break
		sleep 3
	done
	if grep -q "923000000001" <<<"$convs"; then
		ok "the conversation reached the inbox"
	else
		# Distinguish a broken pipeline from an exhausted provider quota. The
		# whole turn runs in one transaction, so an LLM failure rolls the
		# conversation back and this check fails for a reason that is not the
		# pipeline's fault -- and takes the customer's message with it.
		dlq=$(psql_q "select count(*) from failed_jobs where function='process_conversation' and error like '%429%' and created_at > now() - interval '5 minutes'")
		if [[ "${dlq:-0}" -gt 0 ]]; then
			no "the conversation reached the inbox" \
				"LLM provider returned 429 (quota): $dlq job(s) in the DLQ. An environment limit, not a pipeline defect -- but the rollback also discarded the message. See 'Known faults' in docs/E2E-LIVE-TEST-PLAN.md."
		else
			no "the conversation reached the inbox" "chat not listed after 60s; check the worker log"
		fi
	fi

	# The reply itself cannot be delivered: the session is unlinked, so the send
	# fails by design. Persisting the inbound message is what matters here.
	stored=$(psql_q "select count(*) from messages m join conversations c on c.id=m.conversation_id where c.chat_id='923000000001@c.us'")
	if [[ "${stored:-0}" -gt 0 ]]; then
		ok "the inbound message was persisted ($stored row(s))"
	else
		no "the inbound message was persisted" "no messages row for the synthetic chat"
	fi

	if [[ "$KEEP" -eq 0 ]]; then
		psql_q "delete from messages where conversation_id in (select id from conversations where chat_id like '92300000000%')" >/dev/null
		psql_q "delete from conversations where chat_id like '92300000000%'" >/dev/null
		if [[ "$CREATED_SESSION" -eq 1 ]]; then
			# There is no session-delete endpoint (deliberately: an owner should
			# not be able to drop a linked number by accident), so tear it down
			# in WAHA directly. Stopping is not enough -- only DELETE removes the
			# session directory, and stopping alone leaked a directory per run.
			waha_key=$(grep '^WAHA_API_KEY=' "$ENV_FILE_FOR_WAHA" 2>/dev/null | tail -1 | cut -d= -f2)
			[[ -n "$waha_key" ]] && curl -s -o /dev/null --max-time 30 \
				-X DELETE "$WAHA_URL/api/sessions/$SESSION_NAME" -H "X-Api-Key: $waha_key"
			psql_q "delete from whatsapp_sessions where session_name='$SESSION_NAME'" >/dev/null
		fi
		ok "synthetic conversations cleaned up"
	fi
fi

# --------------------------------------------------------------------------- #
phase "Result"
# --------------------------------------------------------------------------- #
printf '  %s passed, %s failed, %s skipped\n' "$(green "$PASS")" "$(red "$FAIL")" "$(yellow "$SKIP")"
if [[ "$FAIL" -gt 0 ]]; then
	printf '\n  Failed:\n'
	for n in "${FAILED_NAMES[@]}"; do printf '    - %s\n' "$n"; done
	printf '\n  Next: docs/E2E-LIVE-TEST-PLAN.md has what each check means.\n'
	exit 1
fi
printf '\n  Everything automatable passed. Part 2 of docs/E2E-LIVE-TEST-PLAN.md\n'
printf '  needs a phone and is the half this cannot reach.\n'
