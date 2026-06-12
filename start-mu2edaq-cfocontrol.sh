#!/usr/bin/env bash
# Start an interactive CFO Control session.
# Launched from a control room desktop icon (Terminal=true) or a shell.
# Target host/port come from config.yaml; CRS_PORT_MACROMAKER (exported
# by the control room crs-app launcher) overrides the port.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARGS=()
if [[ -n "${CRS_PORT_MACROMAKER:-}" ]]; then
  ARGS+=(--port "$CRS_PORT_MACROMAKER")
fi

exec python3 "$SCRIPT_DIR/CFOControl.py" "${ARGS[@]}" "$@"
