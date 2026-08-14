#!/bin/bash
cd ~/qonvo/dashboard
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"
exec env $(grep -v '^#' .env.local | xargs) PORT=3002 HOSTNAME=127.0.0.1 node .next/standalone/server.js
