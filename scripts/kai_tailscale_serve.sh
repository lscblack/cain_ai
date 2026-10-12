#!/usr/bin/env bash
# Expose the KAI backend to YOUR devices over Tailscale — privately, with HTTPS,
# WITHOUT binding the backend to 0.0.0.0. Tailscale proxies the tailnet to
# 127.0.0.1:8001, so the server stays loopback-only and is reachable only by
# devices on your tailnet (your phone included).
#
# PREREQUISITES (you do these — they need your Tailscale account):
#   1. tailscale up                      # log this machine into your tailnet (opens a browser URL)
#   2. In the Tailscale admin console, enable MagicDNS + HTTPS certificates
#      (Settings) so `serve` can get a cert for the ts.net name.
#
# THEN run:  scripts/kai_tailscale_serve.sh [port]
set -euo pipefail

PORT="${1:-8001}"
TS="$(command -v tailscale || echo /snap/bin/tailscale)"

if ! "$TS" status >/dev/null 2>&1; then
  echo "ERROR: Tailscale isn't up. Run:  $TS up" >&2
  exit 1
fi

IP="$("$TS" ip -4 2>/dev/null | head -1 || true)"
DNS="$("$TS" status --json 2>/dev/null | grep -oE '"DNSName":[[:space:]]*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)\."?$/\1/' | sed 's/\.$//')"

echo "Exposing http://127.0.0.1:${PORT} on your tailnet…"
# Serve over HTTPS on the node's ts.net name (tailnet-only; NOT the public internet).
"$TS" serve --bg --https=443 "http://127.0.0.1:${PORT}" || {
  echo "serve failed — enable MagicDNS + HTTPS in the Tailscale admin console, then retry." >&2
  exit 1
}

echo
"$TS" serve status || true
echo
if [ -n "${DNS:-}" ]; then
  echo "  PHONE URL (HTTPS, tailnet-only):  https://${DNS}"
else
  echo "  Tailnet IP: ${IP:-unknown}  — or use the machine's MagicDNS name."
fi
echo "  Put that URL in the KAI app Settings (or tell me and I'll bake it into the APK)."
echo
echo "To stop exposing:  $TS serve --https=443 off"
