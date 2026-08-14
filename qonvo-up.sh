#!/bin/bash
# Bring the whole Qonvo stack up (run after a reboot or a fresh shell).
export PATH="$HOME/.local/bin:$PATH"
cd ~/qonvo
PUBLIC_URL="https://sesame-denial-dumpling.ngrok-free.dev"

# 1. Backend (Docker — persists on its own; this is idempotent insurance)
docker compose up -d postgres redis minio waha api worker scheduler >/dev/null 2>&1
echo "✓ backend up"

# 2. tmux session: dashboard (window 0) + ngrok (window 1)
tmux has-session -t qonvo 2>/dev/null && tmux kill-session -t qonvo
tmux new-session -d -s qonvo -n dashboard "~/qonvo/run-dashboard.sh 2>&1 | tee /tmp/qonvo-dashboard.log"
sleep 5
tmux new-window -t qonvo -n ngrok "export PATH=\$HOME/.local/bin:\$PATH; ngrok http --url=$PUBLIC_URL 3002 --log=/tmp/qonvo-ngrok.log 2>&1"
sleep 6

echo "✓ dashboard in tmux (localhost:3002)"
echo "✓ PUBLIC URL (static): $PUBLIC_URL"
echo "  (attach with: tmux attach -t qonvo)"
