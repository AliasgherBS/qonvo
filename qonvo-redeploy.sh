#!/bin/bash
# Rebuild + restart EVERYTHING from the latest code (backend + frontend).
# Use this whenever you've made changes and want them live.
set -e
export PATH="$HOME/.local/bin:$PATH"
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"

echo "▸ backend (api + worker + scheduler)…"
cd ~/qonvo
docker compose up -d --build api worker scheduler

echo "▸ frontend…"
cd ~/qonvo/dashboard
npm run build
rm -rf .next/standalone/.next/static .next/standalone/public
cp -r public .next/standalone/ && cp -r .next/static .next/standalone/.next/
tmux respawn-window -k -t qonvo:dashboard "~/qonvo/run-dashboard.sh 2>&1 | tee /tmp/qonvo-dashboard.log"

echo "✓ redeployed. Hard-refresh the browser (Ctrl+Shift+R)."
echo "  public: https://qonvo.org"
