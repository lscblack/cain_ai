#!/usr/bin/env bash
# Start a Cloudflare quick tunnel to the local KAI backend and print the public
# HTTPS URL. Quick tunnels are ephemeral — the URL changes each run, so paste
# the printed URL into the mobile app's Settings (or rebuild the APK with
# --dart-define=KAI_BASE_URL=<url>).
#
# For a STABLE url + Cloudflare Access gate, use a NAMED tunnel instead
# (needs a one-time `cloudflared tunnel login` with your Cloudflare account).
set -euo pipefail

PORT="${1:-8001}"
CF="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
LOG="$(mktemp -t kai-tunnel-XXXX.log)"

echo "Starting Cloudflare quick tunnel -> http://127.0.0.1:${PORT}"
"$CF" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" >"$LOG" 2>&1 &
PID=$!
echo "cloudflared pid: $PID   (log: $LOG)"

for _ in $(seq 1 20); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)
  [ -n "${URL:-}" ] && break
  sleep 1
done

if [ -n "${URL:-}" ]; then
  echo
  echo "  PUBLIC URL:  $URL"
  echo "  Put this in the KAI app Settings (Backend Server URL)."
  echo
  echo "Leave this process running. Ctrl-C to stop the tunnel."
  wait "$PID"
else
  echo "Could not detect a tunnel URL. See $LOG" >&2
  exit 1
fi
