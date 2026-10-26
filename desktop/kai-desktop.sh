#!/usr/bin/env bash
# Launches the KAI desktop shell (Electron). Unsets ELECTRON_RUN_AS_NODE, which some IDE terminals export.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec env -u ELECTRON_RUN_AS_NODE "$DIR/node_modules/electron/dist/electron" --no-sandbox "$DIR" "$@"
