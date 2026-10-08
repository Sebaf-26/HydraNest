#!/usr/bin/env bash
#
# Change the Time Machine quota of an existing TimeNest user.
#
# Usage:
#   set-quota.sh <username> <quota_gb>

set -euo pipefail

log() { printf '[set-quota] %s\n' "$*"; }
die() { printf '[set-quota] ERROR: %s\n' "$*" >&2; exit 1; }

if [[ $# -ne 2 ]]; then
    die "usage: $0 <username> <quota_gb>"
fi

USERNAME="$1"
QUOTA_GB="$2"

if [[ ! "$USERNAME" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    die "invalid username"
fi
if [[ ! "$QUOTA_GB" =~ ^[0-9]+$ ]] || (( QUOTA_GB < 10 )); then
    die "invalid quota: must be an integer >= 10 (GB)"
fi

SHARE_CONF="/etc/timenest/shares.d/${USERNAME}.conf"
[[ -f "$SHARE_CONF" ]] || die "no share config for '${USERNAME}'"

if grep -q 'fruit:time machine max size' "$SHARE_CONF"; then
    sed -i "s/^\([[:space:]]*fruit:time machine max size[[:space:]]*=\).*/\1 ${QUOTA_GB}G/" "$SHARE_CONF"
else
    printf '    fruit:time machine max size = %sG\n' "$QUOTA_GB" >> "$SHARE_CONF"
fi
log "set quota for '${USERNAME}' to ${QUOTA_GB}G"

/usr/local/bin/reload-samba.sh
log "done"
