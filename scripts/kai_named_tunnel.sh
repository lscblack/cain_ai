#!/usr/bin/env bash
# Set up a STABLE Cloudflare named tunnel for the KAI backend (replaces the
# ephemeral quick tunnel). Gives a permanent HTTPS hostname you can bake into
# the app and gate with Cloudflare Access.
#
# PREREQUISITES (one-time, YOU do these — they need a browser + your CF account
# and a domain already added to Cloudflare):
#   1. cloudflared tunnel login        # authorizes this machine, writes ~/.cloudflared/cert.pem
#   2. Have a domain/zone in your Cloudflare account (e.g. example.com).
#
# THEN run:   scripts/kai_named_tunnel.sh kai.example.com [tunnel_name] [port]
#   - creates the tunnel, routes DNS to the hostname, writes the config, and
#     (optionally) installs a systemd user service to keep it running.
set -euo pipefail

HOSTNAME="${1:-}"
TUNNEL="${2:-kai}"
PORT="${3:-8001}"
CF="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
CFG_DIR="$HOME/.cloudflared"
CFG="$CFG_DIR/kai-config.yml"

if [ -z "$HOSTNAME" ]; then
  echo "usage: $0 <hostname e.g. kai.example.com> [tunnel_name=kai] [port=8001]" >&2
  exit 2
fi
if [ ! -f "$CFG_DIR/cert.pem" ]; then
  echo "ERROR: not logged in. Run first:  $CF tunnel login" >&2
  exit 1
fi

# Create the tunnel if it doesn't exist; capture its UUID.
if ! "$CF" tunnel list 2>/dev/null | awk '{print $2}' | grep -qx "$TUNNEL"; then
  echo "Creating tunnel '$TUNNEL'…"
  "$CF" tunnel create "$TUNNEL"
fi
UUID="$("$CF" tunnel list 2>/dev/null | awk -v n="$TUNNEL" '$2==n{print $1}' | head -1)"
CRED="$CFG_DIR/$UUID.json"
echo "tunnel: $TUNNEL ($UUID)"

echo "Routing DNS $HOSTNAME -> $TUNNEL …"
"$CF" tunnel route dns "$TUNNEL" "$HOSTNAME"

cat > "$CFG" <<EOF
tunnel: $UUID
credentials-file: $CRED
ingress:
  - hostname: $HOSTNAME
    service: http://127.0.0.1:$PORT
  - service: http_status:404
EOF
echo "wrote $CFG"

echo
echo "Test it:   $CF tunnel --config $CFG run $TUNNEL"
echo "Then the app Settings URL is:  https://$HOSTNAME"
echo
echo "To run it always (systemd user service):"
echo "  cp infra/systemd/kai-tunnel.service ~/.config/systemd/user/"
echo "  systemctl --user daemon-reload && systemctl --user enable --now kai-tunnel"
echo
echo "RECOMMENDED: add a Cloudflare Access policy for $HOSTNAME in the Zero Trust"
echo "dashboard (Access > Applications) so only you can reach it — that's the '+auth' gate."
