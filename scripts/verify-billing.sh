#!/usr/bin/env bash
#
# Prove that what Qonvo records matches what the provider bills.
#
# Drives N messages through the real pipeline on staging, then prints exactly
# what was logged. You compare that against the provider's own dashboard for the
# same window. The point is isolation: nothing else may call the API during the
# run, or the two numbers cannot be compared.
#
# Runs on staging on purpose. Production has a linked WhatsApp number, and
# sending replies to invented phone numbers from a real business line is the
# behaviour that gets numbers banned.
#
#   ./scripts/verify-billing.sh          # 10 messages
#   ./scripts/verify-billing.sh 25
#
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

N="${1:-10}"
API="http://localhost:8010"
PG="qonvo-staging-postgres-1"

q() { docker exec "$PG" psql -U qonvo -d qonvo -tAc "$1" 2>/dev/null | tr -d ' '; }

TOKEN=$(curl -s --max-time 20 -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
	-d '{"email":"owner@dev.dev","password":"dev-password-123"}' |
	python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
if [[ -z "$TOKEN" ]]; then
	echo "Cannot sign in to staging. Run: ./qonvo-staging.sh up && ./qonvo-staging.sh seed" >&2
	exit 1
fi
TENANT=$(curl -s --max-time 20 "$API/api/me" -H "Authorization: Bearer $TOKEN" |
	python3 -c "import sys,json;print(json.load(sys.stdin).get('tenant_id',''))")

SESSION=$(q "select session_name from whatsapp_sessions where tenant_id='$TENANT' limit 1")
if [[ -z "$SESSION" ]]; then
	echo "No session on staging. Run ./scripts/e2e-smoke.sh first — it creates one." >&2
	exit 1
fi
HMAC=$(q "select coalesce(hmac_secret,'') from whatsapp_sessions where session_name='$SESSION'")

BEFORE_T=$(q "select coalesce(sum(tokens),0) from usage_counters")
BEFORE_C=$(q "select coalesce(sum(cost),0) from usage_counters")
BEFORE_R=$(q "select coalesce(sum(messages_out),0) from usage_counters")
STARTED=$(date -u +%H:%M:%SZ)

cat <<EOF
Controlled billing verification — staging
  started        $STARTED UTC
  messages       $N
  model          $(docker exec qonvo-staging-api-1 python -c 'from app.core.config import settings;print(settings.llm_provider+"/"+settings.llm_model)' 2>/dev/null)

Make no other API calls on this key until the run finishes.
EOF

QUESTIONS=(
	"what are your opening hours?"
	"kitne ka hai haircut?"
	"do you do keratin treatment?"
	"where is your branch located?"
	"can I book for tomorrow afternoon?"
	"aap ka refund policy kya hai?"
	"do you have parking?"
	"what services do you offer for men?"
	"are you open on Sunday?"
	"how much for a facial?"
)

for i in $(seq 1 "$N"); do
	Q="${QUESTIONS[$(((i - 1) % ${#QUESTIONS[@]}))]}"
	# A distinct chat per message: same chat would coalesce them into one turn
	# via the debounce window, and we want N billable turns, not one.
	PAYLOAD=$(python3 -c "
import json,sys,time
print(json.dumps({'session': sys.argv[1], 'event': 'message', 'payload': {
    'id': 'verify-'+str(int(time.time()))+'-'+sys.argv[3],
    'from': '9230011100'+sys.argv[3].zfill(2)+'@c.us', 'fromMe': False,
    'body': sys.argv[2], 'timestamp': int(time.time())}}))" "$SESSION" "$Q" "$i")
	SIG=$(python3 -c "
import hmac,hashlib,sys
print(hmac.new(sys.argv[1].encode(), sys.argv[2].encode(), hashlib.sha512).hexdigest())" "$HMAC" "$PAYLOAD")
	curl -s -o /dev/null --max-time 20 -X POST "$API/webhooks/waha" \
		-H 'Content-Type: application/json' -H "X-Webhook-Hmac: $SIG" -d "$PAYLOAD"
	printf '.'
	sleep 1
done
echo " sent"

echo "waiting for the worker to drain..."
for _ in $(seq 1 40); do
	sleep 5
	NOW_R=$(q "select coalesce(sum(messages_out),0) from usage_counters")
	[[ $((NOW_R - BEFORE_R)) -ge "$N" ]] && break
done

AFTER_T=$(q "select coalesce(sum(tokens),0) from usage_counters")
AFTER_C=$(q "select coalesce(sum(cost),0) from usage_counters")
AFTER_R=$(q "select coalesce(sum(messages_out),0) from usage_counters")
FINISHED=$(date -u +%H:%M:%SZ)

D_T=$((AFTER_T - BEFORE_T))
D_R=$((AFTER_R - BEFORE_R))
D_C=$(python3 -c "print(f'{$AFTER_C - $BEFORE_C:.6f}')")

cat <<EOF

What Qonvo recorded
  window         $STARTED to $FINISHED UTC
  replies        $D_R of $N
  tokens         $D_T
  cost           \$$D_C
  per reply      $([[ $D_R -gt 0 ]] && python3 -c "print(f'{$D_T/$D_R:.0f} tokens, \${$D_C/$D_R:.6f}')" || echo "n/a")

Now compare on the provider dashboard for that window:
  https://platform.openai.com/usage    (group by model; it can lag by up to an hour)

  Tokens should match closely. Small differences are expected and explainable:
    * a failed turn retries, and a retried call is billed but never recorded
      (the usage row only lands on success)
    * a tool call is a second round trip; both are billed, both are recorded
    * the provider counts calls this script did not make, if anything else ran
EOF
[[ $D_R -lt $N ]] && echo "
  NOTE: only $D_R of $N replies landed. Check: docker logs qonvo-staging-worker-1"
exit 0
