#!/usr/bin/env bash
# Stop CFO Control. The tool is an interactive CLI session, so there is
# normally nothing to stop; kill any stray non-interactive instances and
# exit 0 either way.
set -uo pipefail

PIDS=$(pgrep -f "python3? .*CFOControl.py" || true)
if [[ -n "$PIDS" ]]; then
  echo "Stopping CFOControl instance(s): $PIDS"
  kill $PIDS 2>/dev/null || true
else
  echo "CFOControl is not running."
fi
exit 0
