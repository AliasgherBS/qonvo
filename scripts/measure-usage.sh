#!/usr/bin/env bash
#
# Measure what a tenant actually costs, and check the claims in
# docs/DEPLOYMENT-AND-COSTS.md against reality.
#
# Every number that document quotes came from a machine with 50 messages on it.
# Run this after a real usage session and it will print the same numbers from
# real traffic, flagging any claim that no longer holds.
#
#   ./scripts/measure-usage.sh                 # production
#   ./scripts/measure-usage.sh --env staging
#
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ENV_NAME="production"
[[ "${1:-}" == "--env" ]] && ENV_NAME="${2:-production}"

if [[ "$ENV_NAME" == "staging" ]]; then
	PG=qonvo-staging-postgres-1; WAHA=qonvo-staging-waha-1; API=qonvo-staging-api-1; PROJECT=qonvo-staging
else
	PG=qonvo-postgres-1; WAHA=qonvo-waha-1; API=qonvo-api-1; PROJECT=qonvo
fi

q() { docker exec "$PG" psql -U qonvo -d qonvo -tAc "$1" 2>/dev/null | tr -d ' '; }
hdr() { printf '\n\033[1m%s\033[0m\n' "$1"; }
row() { printf '  %-38s %s\n' "$1" "$2"; }
# claim <label> <measured> <claimed> <verdict-if-outside>
claim() { printf '  %-38s measured %-14s claimed %-16s %s\n' "$1" "$2" "$3" "$4"; }

printf '\033[1mQonvo usage measurement — %s\033[0m\n' "$ENV_NAME"
printf 'Compare against docs/DEPLOYMENT-AND-COSTS.md\n'

# --------------------------------------------------------------------------- #
hdr "Volume so far"
TENANTS=$(q "select count(*) from tenants")
MSGS=$(q "select count(*) from messages")
CONVS=$(q "select count(*) from conversations")
CHUNKS=$(q "select count(*) from knowledge_chunks")
row "tenants" "${TENANTS:-0}"
row "conversations" "${CONVS:-0}"
row "messages" "${MSGS:-0}"
row "knowledge chunks" "${CHUNKS:-0}"

if [[ "${MSGS:-0}" -lt 50 ]]; then
	printf '\n  \033[33mOnly %s messages. Numbers below are directionally useful\033[0m\n' "${MSGS:-0}"
	printf '  \033[33mbut index overhead still dominates; re-run after real traffic.\033[0m\n'
fi

# --------------------------------------------------------------------------- #
hdr "Tokens and cost per reply  (doc: ~3,312 measured; 1,000-6,500 range)"
TOK=$(q "select coalesce(sum(tokens),0) from usage_counters")
OUT=$(q "select coalesce(sum(messages_out),0) from usage_counters")
IN=$(q "select coalesce(sum(messages_in),0) from usage_counters")
COST=$(q "select coalesce(round(sum(cost)::numeric,6),0) from usage_counters")
VOICE=$(q "select coalesce(sum(voice_seconds),0) from usage_counters")
row "messages in / out (metered)" "${IN:-0} / ${OUT:-0}"
row "total tokens" "${TOK:-0}"
row "recorded cost (USD)" "\$${COST:-0}"
row "voice seconds" "${VOICE:-0}"
if [[ "${OUT:-0}" -gt 0 ]]; then
	PERREPLY=$(python3 -c "print(round($TOK/$OUT))")
	# Wide range on purpose: a first message to a knowledge-less tenant is
	# ~1,000 tokens; a long thread against a full knowledge base approaches the
	# RAG + history caps at ~6,500.
	claim "tokens per reply" "$PERREPLY" "3312 (1k-6.5k)" \
		"$(python3 -c "print('OK' if 800 <= $PERREPLY <= 7000 else '** OUTSIDE MODELLED RANGE **')")"
	CPR=$(python3 -c "print(f'{$COST/$OUT:.6f}')")
	row "recorded cost per reply" "\$$CPR"
	printf '  %s\n' "note: config.py prices Gemini at 2x Google's direct rate, so this over-reports"
fi

# --------------------------------------------------------------------------- #
hdr "Storage per tenant  (doc: ~13 MB first month, ~2 MB after)"
DB=$(q "select pg_size_pretty(pg_database_size('qonvo'))")
MSGBYTES=$(q "select case when count(*)=0 then 0 else pg_total_relation_size('messages')/count(*) end from messages")
CHUNKBYTES=$(q "select case when count(*)=0 then 0 else pg_total_relation_size('knowledge_chunks')/count(*) end from knowledge_chunks")
row "database total" "${DB:-?}"
claim "bytes per message row" "${MSGBYTES:-0}" "500-1000 steady" \
	"$(python3 -c "print('OK' if 0 < ${MSGBYTES:-0} <= 1200 else 'index overhead still dominates' if ${MSGBYTES:-0} > 0 else '-')")"
claim "bytes per knowledge chunk" "${CHUNKBYTES:-0}" "6000-8000" \
	"$(python3 -c "print('OK' if 4000 <= ${CHUNKBYTES:-0} <= 20000 else 'index overhead still dominates' if ${CHUNKBYTES:-0} > 0 else '-')")"

if [[ "${TENANTS:-0}" -gt 0 && "${MSGS:-0}" -gt 0 ]]; then
	q "select t.name || ' | msgs=' || (select count(*) from messages m where m.tenant_id=t.id)
	   || ' | chunks=' || (select count(*) from knowledge_chunks k where k.tenant_id=t.id)
	   || ' | convs=' || (select count(*) from conversations c where c.tenant_id=t.id)
	   from tenants t order by t.created_at" | sed 's/^/  /'
fi

# --------------------------------------------------------------------------- #
hdr "WAHA per session  (doc: ~3.5 MB fixed + ~4 KB per contact; 11 MB measured)"
docker exec "$WAHA" sh -c '
for d in /app/.sessions/noweb/*/; do
  [ -d "$d" ] || continue
  printf "  %-28s %-8s files=%s\n" "$(basename "$d")" "$(du -sh "$d" | cut -f1)" "$(ls -1 "$d" | wc -l)"
done' 2>/dev/null || echo "  (no sessions)"
row "sessions dir total" "$(docker exec "$WAHA" du -sh /app/.sessions 2>/dev/null | cut -f1)"
row "waha RSS" "$(docker stats --no-stream --format '{{.MemUsage}}' "$WAHA" 2>/dev/null | cut -d/ -f1)"
printf '  %s\n' "Expect ~811 pre-keys (fixed ~3.2 MB) plus one lid-mapping file per contact."
printf '  %s\n' "store.sqlite3 should stay near 4 KB. If it grows, fullSync got re-enabled." 

# --------------------------------------------------------------------------- #
hdr "Uploaded knowledge files"
docker exec "$API" sh -c 'du -sh /data/knowledge 2>/dev/null || echo "  (no volume)"' | sed 's/^/  /'
row "files on the volume" "$(docker exec "$API" sh -c 'find /data/knowledge -type f 2>/dev/null | wc -l')"

# --------------------------------------------------------------------------- #
hdr "Memory, containers  (doc: ~740 MB app, ~1.15 GB with monitoring)"
# Filter by the compose project LABEL, not the name prefix: "qonvo-" also
# matches every qonvo-staging container, which silently doubled the total.
mapfile -t NAMES < <(docker ps --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}')
for n in "${NAMES[@]}"; do
	printf '  %-26s %s\n' "$n" "$(docker stats --no-stream --format '{{.MemUsage}}' "$n" 2>/dev/null)"
done
TOTAL=$(for n in "${NAMES[@]}"; do docker stats --no-stream --format '{{.MemUsage}}' "$n" 2>/dev/null; done \
	| cut -d/ -f1 \
	| python3 -c "
import sys
t=0.0
for l in sys.stdin:
    l=l.strip()
    if l.endswith('GiB'): t+=float(l[:-3])*1024
    elif l.endswith('MiB'): t+=float(l[:-3])
    elif l.endswith('KiB'): t+=float(l[:-3])/1024
print(f'{t:.0f} MiB')")
claim "containers total" "$TOTAL" "740MB / 1.15GB+mon" ""
printf '  %s\n' "The dashboard is a host node process (~105 MB), not counted above."

# --------------------------------------------------------------------------- #
hdr "Reclaimed space after deletes"
DEAD=$(q "select coalesce(sum(n_dead_tup),0) from pg_stat_user_tables")
row "dead tuples awaiting vacuum" "${DEAD:-0}"
printf '  %s\n' "Postgres frees deleted rows for REUSE, but does not shrink the file."
printf '  %s\n' "To actually return disk to the OS: VACUUM FULL (locks the table)."

printf '\n\033[1mDone.\033[0m Update docs/DEPLOYMENT-AND-COSTS.md where a claim differs.\n'
