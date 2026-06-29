#!/usr/bin/env bash
#
# stop-mu2edaq-cfocontrol.sh - standardized Mu2e control-room stop script.
#
# CFOControl is a one-shot CLI tool (it connects, runs a command, and exits);
# there is no long-running daemon to stop. This script exists for control-room
# naming uniformity and is a graceful no-op.
set -euo pipefail

echo "mu2edaq-CFOControl is a one-shot control tool; there is no persistent"
echo "process to stop."
exit 0
