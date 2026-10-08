#!/usr/bin/env bash
#
# TimeNest - Samba entrypoint
#
# Renders /etc/samba/smb.conf from the template, seeds the passdb and the
# shares directory if this is a fresh install, then starts smbd in the
# foreground so tini can reap it.

set -euo pipefail

log() { printf '[samba] %s\n' "$*"; }
die() { printf '[samba] ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Env defaults
# ---------------------------------------------------------------------------
: "${SERVER_NAME:=TimeNest}"
: "${DEVICE_MODEL:=TimeCapsule8,119}"
: "${SMB_INTERFACES:=}"
: "${LOG_LEVEL:=INFO}"

# Map human log levels to Samba's numeric scale.
case "${LOG_LEVEL^^}" in
    DEBUG)   SAMBA_LOG_LEVEL=3 ;;
    INFO)    SAMBA_LOG_LEVEL=1 ;;
    WARNING) SAMBA_LOG_LEVEL=1 ;;
    ERROR)   SAMBA_LOG_LEVEL=0 ;;
    *)       SAMBA_LOG_LEVEL=1 ;;
esac
export SAMBA_LOG_LEVEL

# `bind interfaces only` makes sense only when interfaces are given.
if [[ -n "$SMB_INTERFACES" ]]; then
    BIND_INTERFACES_ONLY=yes
else
    BIND_INTERFACES_ONLY=no
    SMB_INTERFACES=""
fi
export BIND_INTERFACES_ONLY SMB_INTERFACES
export SERVER_NAME DEVICE_MODEL

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
# HydraNest: only /etc/timenest/shares.d is meant to be bind-mounted (it holds
# the per-user share fragments, which must survive redeploys and be visible
# to the web UI). Templates live in /usr/share/timenest so that mounting a
# volume over /etc/timenest can no longer hide them.
SHARES_DIR=/etc/timenest/shares.d
mkdir -p /etc/samba "$SHARES_DIR" /var/lib/samba/private /var/log/samba /backup

TEMPLATE=/usr/share/timenest/smb.conf.template
[[ -f "$TEMPLATE" ]] || TEMPLATE=/etc/timenest/smb.conf.template
[[ -f "$TEMPLATE" ]] || die "smb.conf template not found"

# The template uses ${VAR} syntax - envsubst only replaces explicitly
# listed vars to avoid accidentally eating literal `$` in comments.
# shellcheck disable=SC2016  # single quotes intentional; envsubst reads literal ${VAR} list
envsubst '${SERVER_NAME} ${DEVICE_MODEL} ${SMB_INTERFACES} ${BIND_INTERFACES_ONLY} ${SAMBA_LOG_LEVEL}' \
    < "$TEMPLATE" \
    > /etc/samba/smb.conf

# Without explicit interfaces, drop the line entirely: rendering
# `interfaces = lo` is misleading and limits nmbd/browsing to loopback.
if [[ "$BIND_INTERFACES_ONLY" == "no" ]]; then
    sed -i '/^[[:space:]]*interfaces[[:space:]]*=/d' /etc/samba/smb.conf
fi

log "rendered /etc/samba/smb.conf"

# Samba does NOT expand wildcards in `include =`, so the template includes a
# generated file that lists every fragment explicitly.
/usr/local/bin/sync-shares.sh
log "backing up to /backup (host BACKUP_PATH)"
log "advertising as '${SERVER_NAME}' / model '${DEVICE_MODEL}'"

# ---------------------------------------------------------------------------
# Seed passdb on first boot so `net` commands do not complain.
# ---------------------------------------------------------------------------
if [[ ! -s /var/lib/samba/passdb.tdb ]]; then
    log "initializing fresh passdb"
    touch /var/lib/samba/smbpasswd
fi

# ---------------------------------------------------------------------------
# Recreate POSIX accounts. /etc/passwd lives in the container's ephemeral
# filesystem, while passdb.tdb and shares.d are persistent: after a redeploy
# `valid users` / `force user` would point at users that no longer exist.
# UID/GID are taken from the owner of /backup/<user> so existing Time Machine
# data stays accessible.
# ---------------------------------------------------------------------------
USERNAME_RE='^[a-z_][a-z0-9_-]{0,31}$'

restore_user() {
    local name="$1" uid="" gid="" dir="/backup/$1"
    [[ "$name" =~ $USERNAME_RE ]] || return 0
    id "$name" &>/dev/null && return 0

    if [[ -d "$dir" ]]; then
        uid=$(stat -c %u "$dir")
        gid=$(stat -c %g "$dir")
        # Root-owned dir means we know nothing useful about the old IDs.
        [[ "$uid" == 0 ]] && uid="" && gid=""
    fi

    if ! getent group "$name" >/dev/null; then
        if [[ -n "$gid" ]] && ! getent group "$gid" >/dev/null; then
            groupadd --system --gid "$gid" "$name"
        else
            groupadd --system "$name"
        fi
    fi

    if [[ -n "$uid" ]] && ! getent passwd "$uid" >/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin \
            --uid "$uid" --gid "$name" "$name"
    else
        useradd --system --no-create-home --shell /usr/sbin/nologin \
            --gid "$name" "$name"
        if [[ -d "$dir" ]]; then
            log "WARNING: original UID for '${name}' unavailable, re-owning ${dir}"
            chown -R "${name}:${name}" "$dir"
        fi
    fi
    log "restored POSIX user '${name}' ($(id "$name"))"
}

shopt -s nullglob
declare -A KNOWN_USERS=()
for conf in "$SHARES_DIR"/*.conf; do
    KNOWN_USERS["$(basename "$conf" .conf)"]=1
done
while IFS=: read -r name _; do
    [[ -n "$name" ]] && KNOWN_USERS["$name"]=1
done < <(pdbedit -L 2>/dev/null || true)
shopt -u nullglob

for name in "${!KNOWN_USERS[@]}"; do
    restore_user "$name"
done
log "${#KNOWN_USERS[@]} user(s) known"

# Verify the config parses before we exec smbd. A bad template means no
# restart loop panic - we fail fast with a readable error.
if ! testparm -s /etc/samba/smb.conf > /dev/null 2>&1; then
    log "testparm output:"
    testparm -s /etc/samba/smb.conf || true
    die "smb.conf failed to parse; refusing to start"
fi

# ---------------------------------------------------------------------------
# Handle SIGTERM cleanly - smbd's default is graceful on SIGTERM.
# ---------------------------------------------------------------------------
shutdown() {
    log "received shutdown signal, stopping smbd"
    kill -TERM "${SMBD_PID:-0}" 2>/dev/null || true
    wait "${SMBD_PID:-0}" 2>/dev/null || true
    exit 0
}
trap shutdown TERM INT

# `--log-stdout` was renamed `--debug-stdout` in Samba 4.15; Debian bookworm
# ships 4.17 and rejects the old flag, so smbd died right after start.
# Pick whichever the installed smbd supports.
SMBD_ARGS=(--foreground --no-process-group --configfile=/etc/samba/smb.conf)
SMBD_HELP=$(smbd --help 2>&1 || true)
if grep -q -- '--debug-stdout' <<<"$SMBD_HELP"; then
    SMBD_ARGS+=(--debug-stdout)
elif grep -q -- '--log-stdout' <<<"$SMBD_HELP"; then
    SMBD_ARGS+=(--log-stdout)
fi

log "starting smbd (foreground): smbd ${SMBD_ARGS[*]}"
smbd "${SMBD_ARGS[@]}" &
SMBD_PID=$!

wait "$SMBD_PID"
