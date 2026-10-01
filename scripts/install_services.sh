#!/usr/bin/env bash
# Install KAI as systemd *user* services: backend :8001, frontend :5174.
# Run as your normal user (NOT root).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/infra/systemd/kai-backend.service"  "$HOME/.config/systemd/user/"
cp "$HERE/infra/systemd/kai-frontend.service" "$HOME/.config/systemd/user/"

# free the ports from any manually-started instances
for port in 8001 5174; do
  pid=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | head -1 || true)
  [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null || true
done

systemctl --user daemon-reload
systemctl --user enable --now kai-backend.service kai-frontend.service

echo
echo ">>> To start at BOOT (before login), run ONCE:  sudo loginctl enable-linger $USER"
echo "Backend  http://127.0.0.1:8001   Frontend http://127.0.0.1:5174"
echo "Logs: journalctl --user -u kai-backend -f   |   journalctl --user -u kai-frontend -f"
