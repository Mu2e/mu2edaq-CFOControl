#!/usr/bin/env bash
#
# start-mu2edaq-cfocontrol.sh - standardized Mu2e control-room start script.
#
# CFOControl is a one-shot CLI control tool (connect to the MacroMaker, run a
# command, exit), launched in a terminal by `crs-app start cfocontrol`. This
# wrapper forwards CRS_PORT_MACROMAKER as the MacroMaker UDP --port; any extra
# arguments (e.g. --fe, --cmd) are passed through.
#
# Port precedence: CRS_PORT_MACROMAKER env > built-in default (matches apps.yaml).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CRS_PORT_MACROMAKER="${CRS_PORT_MACROMAKER:-5000}"

PY=python3
[[ -x ./venv/bin/python ]] && PY=./venv/bin/python

exec "$PY" CFOControl.py --port "$CRS_PORT_MACROMAKER" "$@"
