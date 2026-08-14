#!/bin/bash
# Bring the whole Qonvo stack up (run after a reboot or a fresh shell).
export PATH="$HOME/.local/bin:$PATH"
cd ~/qonvo

# 1. Backend (Docker — persists on its own, this is just idempotent insurance)
docker compose up -d postgres redis minio waha api worker scheduler >/dev/null 2>&1
echo "✓ backend up"

# 2. tmux session: dashboard (window 0) + zrok (window 1)
tmux has-session -t qonvo 2>/dev/null && tmux kill-session -t qonvo
tmux new-session -d -s qonvo -n dashboard "~/qonvo/run-dashboard.sh 2>&1 | tee /tmp/qonvo-dashboard.log"
sleep 5
tmux new-window -t qonvo -n zrok "export PATH=\$HOME/.local/bin:\$PATH; zrok share public http://localhost:3002 --headless 2>&1 | tee /tmp/qonvo-zrok.log"
sleep 7

URL=$(grep -oiE '[a-z0-9-]+\.shares\.zrok\.io' /tmp/qonvo-zrok.log | head -1)
echo "✓ dashboard in tmux (localhost:3002)"
echo "✓ PUBLIC URL: https://$URL"
echo "  (attach with: tmux attach -t qonvo)"
