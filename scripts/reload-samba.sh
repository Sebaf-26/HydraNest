#!/usr/bin/env bash
#
# Re-sync the share include list and ask smbd to re-read its configuration.

set -euo pipefail

/usr/local/bin/sync-shares.sh

if pidof smbd >/dev/null; then
    printf '[reload] reloading smbd\n'
    smbcontrol smbd reload-config 2>/dev/null || pkill -HUP smbd || true
fi
