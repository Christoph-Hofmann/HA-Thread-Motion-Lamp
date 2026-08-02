#!/bin/bash
# ---------------------------------------------------------------------------
# Deploy custom_components/matter_motion_lamp to the HA host and restart HA
# core to pick it up.
#
# A `git push` to this repo does NOT update the live instance — HA doesn't
# pull from git at all. /homeassistant/custom_components/matter_motion_lamp
# on the host is a plain directory kept in sync by hand (there's no HACS/
# git-checkout deployment set up), so it drifts from this repo unless
# something re-syncs it after every change. This script is that something —
# run it after committing (and ideally pushing) local changes.
#
# Requires: SSH root access to the HA host (same as ota_update.sh,
# list_nodes.sh).
#
# Usage:
#   ./sync.sh          # sync + restart HA core
#   ./sync.sh --no-restart   # sync only, skip the HA core restart
# ---------------------------------------------------------------------------
set -euo pipefail

HA_HOST="10.20.8.159"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DIR="$SCRIPT_DIR/custom_components/matter_motion_lamp"
REMOTE_DIR="/homeassistant/custom_components/matter_motion_lamp"

if [ ! -d "$LOCAL_DIR" ]; then
    echo "error: $LOCAL_DIR not found — run this from the ha-motionlamp-thread repo" >&2
    exit 1
fi

echo "Syncing $LOCAL_DIR -> root@$HA_HOST:$REMOTE_DIR"
rsync -az --delete \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$LOCAL_DIR/" "root@$HA_HOST:$REMOTE_DIR/"

if [ "${1:-}" = "--no-restart" ]; then
    echo "Synced. Skipping HA core restart (--no-restart)."
    exit 0
fi

echo "Restarting Home Assistant core..."
ssh -o BatchMode=yes "root@$HA_HOST" "ha core restart"
echo "Restart triggered — give HA a minute or two to come back up."
