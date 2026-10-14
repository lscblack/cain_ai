#!/usr/bin/env bash
# Print KAI's current public HTTPS URLs (Cloudflare quick tunnels).
#
# - FRONTEND (web app) is served by the `kai-frontend-tunnel` systemd service
#   and already proxies /api -> backend, so this one URL is the whole web app.
# - BACKEND (absolute API URL for the mobile app / Pair-mobile QR) is a separate
#   tunnel to :8001.
#
# Quick-tunnel URLs are EPHEMERAL — they change whenever the tunnel restarts.
set -euo pipefail

fe=$(journalctl --user -u kai-frontend-tunnel --no-pager 2>/dev/null \
      | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)
be=$(pgrep -af 'cloudflared.*8001' 2>/dev/null >/dev/null \
      && journalctl --user -u kai-backend-tunnel --no-pager 2>/dev/null \
         | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)

echo "KAI public URLs (Cloudflare quick tunnels):"
echo "  WEB APP (open in a browser):  ${fe:-<frontend tunnel not running>}"
if [ -n "${be:-}" ]; then
  echo "  BACKEND API (mobile / QR):    ${be}"
fi
echo
echo "Note: quick-tunnel URLs change on restart. For a stable URL + access gate,"
echo "set up a NAMED tunnel (needs a one-time 'cloudflared tunnel login')."
