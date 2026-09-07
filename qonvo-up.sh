#!/bin/bash
# Bring the whole Qonvo stack up (run after a reboot or a fresh shell).
#
# Public access is a Cloudflare Tunnel, which replaced the ngrok tunnel when the
# domain went live. The tunnel dials outward, so no ports are opened and no
# public IP is needed — which is what makes this work from a home connection
# behind CGNAT. Hostname routing lives in ~/.cloudflared/config.yml:
#
#     qonvo.org      -> localhost:3002   (the dashboard host process)
#     api.qonvo.org  -> localhost:8000   (the API)
#
# See docs/GOING-LIVE-ON-A-DOMAIN.md.
export PATH="$HOME/.local/bin:$PATH"
cd ~/qonvo
PUBLIC_URL="https://qonvo.org"
API_URL="https://api.qonvo.org"

# 1. Backend (Docker — persists on its own; this is idempotent insurance)
docker compose up -d postgres redis minio waha api worker scheduler >/dev/null 2>&1
echo "✓ backend up"

# 2. tmux session: dashboard (window 0) + the tunnel (window 1)
tmux has-session -t qonvo 2>/dev/null && tmux kill-session -t qonvo
tmux new-session -d -s qonvo -n dashboard "~/qonvo/run-dashboard.sh 2>&1 | tee /tmp/qonvo-dashboard.log"
sleep 5
tmux new-window -t qonvo -n cloudflared \
	"export PATH=\$HOME/.local/bin:\$PATH; cloudflared tunnel run qonvo 2>&1 | tee /tmp/qonvo-cloudflared.log"
sleep 8

echo "✓ dashboard in tmux (localhost:3002)"
echo "✓ tunnel in tmux  → $PUBLIC_URL  ·  $API_URL"
echo "  (attach with: tmux attach -t qonvo)"

# 3. Prove the public path actually works, rather than assuming the tunnel
#    came up. A tunnel that connects but routes nowhere looks identical to a
#    healthy one from here.
for url in "$PUBLIC_URL/login" "$API_URL/readyz"; do
	code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url" 2>/dev/null)
	if [ "$code" = "200" ]; then
		echo "✓ $url"
	else
		echo "✗ $url returned ${code:-no response} — check: tmux attach -t qonvo"
	fi
done
