#!/usr/bin/env bash
#
# Create the email DNS records for qonvo.org on Cloudflare, idempotently.
#
# Everything in docs/EMAIL-SETUP.md §3 and §5 that is a DNS record lives here,
# so the records are reproducible rather than a thing someone once clicked.
#
#   export CLOUDFLARE_API_TOKEN=...        # Zone:DNS:Edit + Zone:Zone:Read
#   ./scripts/dns-email.sh check           # what exists today, and what is wrong
#   ./scripts/dns-email.sh zoho-mx         # the three Zoho MX records
#   ./scripts/dns-email.sh spf root  "v=spf1 include:zoho.com ~all"
#   ./scripts/dns-email.sh spf send  "v=spf1 include:zeptomail.zoho.com ~all"
#   ./scripts/dns-email.sh dkim zmail._domainkey       "v=DKIM1; k=rsa; p=..."
#   ./scripts/dns-email.sh dkim zmail._domainkey.send  "v=DKIM1; k=rsa; p=..."
#   ./scripts/dns-email.sh dmarc                       # both names, p=none
#   ./scripts/dns-email.sh txt <name> <value>          # domain verification
#
# The DKIM and verification values are generated per account and cannot be
# derived, so those two commands take what the vendor shows you. Everything
# else is fixed and needs no input.
#
# SAFETY: this script only ever writes MX and TXT. The tunnel's CNAME records
# for qonvo.org and api.qonvo.org are what make the site reachable, and nothing
# here can touch them -- see guard_type().
set -euo pipefail

ZONE_NAME="${QONVO_DNS_ZONE:-qonvo.org}"
API="https://api.cloudflare.com/client/v4"
HELPERS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cf_dns.py"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
	echo "set CLOUDFLARE_API_TOKEN -- needs Zone:DNS:Edit + Zone:Zone:Read on $ZONE_NAME" >&2
	echo "  Cloudflare dashboard -> My Profile -> API Tokens -> Create -> 'Edit zone DNS' template" >&2
	exit 1
fi

die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()  { printf '\033[32m✓\033[0m %s\n' "$*"; }
inf() { printf '  %s\n' "$*"; }

cf() {
	local method="$1" path="$2" body="${3:-}"
	local args=(-sS -X "$method" "$API$path"
		-H "Authorization: Bearer $CLOUDFLARE_API_TOKEN"
		-H "Content-Type: application/json")
	[[ -n "$body" ]] && args+=(--data "$body")
	curl "${args[@]}"
}

# Refuse to write anything that could take the site down. Only mail records.
guard_type() {
	case "$1" in
		MX|TXT) ;;
		*) die "refusing to write a $1 record: this script writes mail records only" ;;
	esac
}

py() { python3 "$HELPERS" "$@"; }

zone_id() { cf GET "/zones?name=$ZONE_NAME" | py zone-id; }

# fqdn <name>  --  "@" or "root" means the apex; anything else gets the zone appended
fqdn() {
	case "$1" in
		@|root|"$ZONE_NAME") echo "$ZONE_NAME" ;;
		*."$ZONE_NAME")      echo "$1" ;;
		*)                   echo "$1.$ZONE_NAME" ;;
	esac
}

# upsert <type> <name> <content> [priority]
# Re-running is a no-op rather than a duplicate. Two SPF TXT records on one
# name is illegal and fails closed, which is exactly the accident this avoids.
upsert() {
	local type="$1" name="$2" content="$3" prio="${4:-}"
	guard_type "$type"
	local zid full existing match_id body
	zid="$(zone_id)" || die "could not resolve zone $ZONE_NAME"
	full="$(fqdn "$name")"

	existing="$(cf GET "/zones/$zid/dns_records?type=$type&name=$full" | py result)" \
		|| die "lookup failed for $type $full"
	match_id="$(py match-id "$existing" "$type" "$content")"
	body="$(py body "$type" "$full" "$content" "$prio")"

	if [[ -n "$match_id" ]]; then
		cf PUT "/zones/$zid/dns_records/$match_id" "$body" | py result >/dev/null \
			|| die "update failed: $type $full"
		ok "$type $full ${prio:+prio=$prio }-> updated"
	else
		cf POST "/zones/$zid/dns_records" "$body" | py result >/dev/null \
			|| die "create failed: $type $full"
		ok "$type $full ${prio:+prio=$prio }-> created"
	fi
}

cmd_check() {
	local zid; zid="$(zone_id)" || die "could not resolve zone $ZONE_NAME"
	ok "zone $ZONE_NAME ($zid)"
	cf GET "/zones/$zid/dns_records?per_page=200" | py audit
	printf '\n\033[1mEmail Routing\033[0m\n'
	cf GET "/zones/$zid/email/routing" | py routing
}

cmd_zoho_mx() {
	# docs/EMAIL-SETUP.md §3.5
	upsert MX @ mx.zoho.com  10
	upsert MX @ mx2.zoho.com 20
	upsert MX @ mx3.zoho.com 50
	inf "Cloudflare never proxies MX, so there is no grey cloud to set here."
}

cmd_spf() {
	local where="${1:?root|send}" value="${2:?the SPF string}"
	case "$where" in
		root) upsert TXT @    "$value" ;;
		send) upsert TXT send "$value" ;;
		*) die "spf takes 'root' (Zoho) or 'send' (ZeptoMail)" ;;
	esac
	inf "One SPF record per name, always. A second is illegal and fails closed."
}

cmd_dkim() { upsert TXT "${1:?name, e.g. zmail._domainkey}" "${2:?the DKIM value}"; }
cmd_txt()  { upsert TXT "${1:?name}" "${2:?value}"; }

cmd_dmarc() {
	local rua="${1:-admin@$ZONE_NAME}"
	upsert TXT _dmarc      "v=DMARC1; p=none; rua=mailto:$rua"
	upsert TXT _dmarc.send "v=DMARC1; p=none; rua=mailto:$rua"
	inf "p=none on purpose. Tighten only after a couple of weeks of clean reports."
}

case "${1:-check}" in
	check)   cmd_check ;;
	zoho-mx) cmd_zoho_mx ;;
	spf)     shift; cmd_spf "$@" ;;
	dkim)    shift; cmd_dkim "$@" ;;
	dmarc)   shift; cmd_dmarc "$@" ;;
	txt)     shift; cmd_txt "$@" ;;
	*)       sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
