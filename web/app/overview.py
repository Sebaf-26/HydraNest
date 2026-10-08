"""View models shared by the Overview, Backups, Clients and Quotas pages.

Everything is derived from real data: share fragments (users, quotas), the
backup folders (Time Machine bundles and snapshots), live smbstatus sessions
and the monitor's "last seen" history. Nothing is invented: when a value is
unknown the templates show a dash.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import disks, timemachine
from .config import Settings
from .monitor import LiveState
from .samba_mgr import TimeNestUser

STALE_DAYS = 7
QUOTA_WARN_PCT = 90
DISK_WARN_PCT = 90
DISK_CRIT_PCT = 97
IN_PROGRESS_SECONDS = 5 * 60


@dataclass(slots=True)
class UserRow:
    user: TimeNestUser
    quota_bytes: int
    pct: float
    bundles: tuple[timemachine.Bundle, ...]

    @property
    def free_bytes(self) -> int:
        return max(self.quota_bytes - self.user.used_bytes, 0)


@dataclass(slots=True)
class Client:
    name: str
    model: str
    model_id: str | None
    is_laptop: bool
    user: str
    online: bool
    ip: str | None
    hostname: str | None
    last_seen_ts: int | None
    last_backup_ts: int | None
    size_bytes: int
    snapshots: int
    status: str  # ok | stale | never | failed | running


@dataclass(slots=True)
class BackupEvent:
    mac_name: str
    is_laptop: bool
    user: str
    ts: int
    bytes_copied: int | None
    status: str  # success | running | updated


@dataclass(slots=True)
class Health:
    level: str  # ok | warn | crit
    title: str
    detail: str
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Overview:
    users: list[UserRow]
    clients: list[Client]
    events: list[BackupEvent]
    health: Health
    disk: disks.DiskUsage | None
    backups_bytes: int
    live: LiveState

    @property
    def capacity_bytes(self) -> int:
        """Space Time Machine can use: what backups take plus what is free.

        Other data on the same volume is deliberately left out, so the
        storage figures only talk about backups.
        """
        return self.backups_bytes + (self.disk.free_bytes if self.disk else 0)

    @property
    def backup_pct(self) -> float:
        cap = self.capacity_bytes
        return round(self.backups_bytes / cap * 100, 1) if cap else 0.0

    @property
    def online_clients(self) -> list[Client]:
        return [c for c in self.clients if c.online]

    @property
    def bundles(self) -> list[timemachine.Bundle]:
        out = [b for row in self.users for b in row.bundles]
        out.sort(key=lambda b: b.last_backup_ts or 0, reverse=True)
        return out


def build(settings: Settings, users: list[TimeNestUser], live: LiveState) -> Overview:
    now = int(time.time())
    online_users = {s.user: s for s in live.sessions}

    rows: list[UserRow] = []
    for u in users:
        scan = timemachine.scan_user(u.path)
        quota_bytes = u.quota_gb * 1024**3
        pct = (u.used_bytes / quota_bytes * 100) if quota_bytes else 0.0
        rows.append(UserRow(user=u, quota_bytes=quota_bytes, pct=round(pct, 1), bundles=scan.bundles))

    clients: list[Client] = []
    events: list[BackupEvent] = []
    users_with_bundle: set[str] = set()
    for row in rows:
        name = row.user.username
        session = online_users.get(name)
        seen = live.seen.get(name)
        for b in row.bundles:
            users_with_bundle.add(name)
            running = bool(
                session
                and b.last_activity_ts
                and now - b.last_activity_ts < IN_PROGRESS_SECONDS
            )
            clients.append(
                Client(
                    name=b.mac_name,
                    model=b.model_name,
                    model_id=b.model_id,
                    is_laptop=b.is_laptop,
                    user=name,
                    online=session is not None,
                    ip=(session.ip if session else (seen.ip if seen else None)),
                    hostname=seen.hostname if seen else None,
                    last_seen_ts=now if session else (seen.last_seen_ts if seen else None),
                    last_backup_ts=b.last_backup_ts,
                    size_bytes=b.size_bytes,
                    snapshots=len(b.snapshots),
                    status=_client_status(b, running, now),
                )
            )
            if running and b.last_activity_ts:
                events.append(BackupEvent(b.mac_name, b.is_laptop, name, b.last_activity_ts, None, "running"))
            if b.snapshots:
                for snap in b.snapshots[:10]:
                    events.append(
                        BackupEvent(b.mac_name, b.is_laptop, name, snap.completed_ts, snap.bytes_copied, "success")
                    )
            elif b.last_activity_ts and not running:
                events.append(BackupEvent(b.mac_name, b.is_laptop, name, b.last_activity_ts, None, "updated"))

    # Users connected (now or before) whose Mac hasn't created a bundle yet.
    for name in sorted(set(online_users) | set(live.seen)):
        if name in users_with_bundle or not any(r.user.username == name for r in rows):
            continue
        session = online_users.get(name)
        seen = live.seen.get(name)
        clients.append(
            Client(
                name=(seen.hostname if seen and seen.hostname else name),
                model="Mac",
                model_id=None,
                is_laptop=False,
                user=name,
                online=session is not None,
                ip=(session.ip if session else (seen.ip if seen else None)),
                hostname=seen.hostname if seen else None,
                last_seen_ts=now if session else (seen.last_seen_ts if seen else None),
                last_backup_ts=None,
                size_bytes=0,
                snapshots=0,
                status="never",
            )
        )

    clients.sort(key=lambda c: (not c.online, -(c.last_seen_ts or c.last_backup_ts or 0)))
    events.sort(key=lambda e: e.ts, reverse=True)

    disk = disks.usage(settings.backup_path)
    backups_bytes = sum(r.user.used_bytes for r in rows)
    free_bytes = disk.free_bytes if disk else 0
    capacity = backups_bytes + free_bytes
    backup_pct = (backups_bytes / capacity * 100) if capacity else 0.0

    return Overview(
        users=sorted(rows, key=lambda r: r.user.used_bytes, reverse=True),
        clients=clients,
        events=events,
        health=_health(live, rows, clients, disk, backup_pct),
        disk=disk,
        backups_bytes=backups_bytes,
        live=live,
    )


def _client_status(b: timemachine.Bundle, running: bool, now: int) -> str:
    if running:
        return "running"
    if b.verification == "failed":
        return "failed"
    if not b.last_backup_ts:
        return "never"
    if now - b.last_backup_ts > STALE_DAYS * 86400:
        return "stale"
    return "ok"


def _health(
    live: LiveState,
    rows: list[UserRow],
    clients: list[Client],
    disk: disks.DiskUsage | None,
    backup_pct: float,
) -> Health:
    crit: list[str] = []
    warn: list[str] = []
    if not live.samba_ok:
        crit.append("Samba is not responding")
    if disk is None:
        crit.append("Backup volume is not mounted")
    elif backup_pct >= DISK_CRIT_PCT:
        crit.append(f"Backup space almost full ({backup_pct:.0f}%)")
    elif backup_pct >= DISK_WARN_PCT:
        warn.append(f"Backup space {backup_pct:.0f}% full")
    for c in clients:
        if c.status == "stale":
            warn.append(f"{c.name}: no backup for more than {STALE_DAYS} days")
        elif c.status == "failed":
            warn.append(f"{c.name}: Time Machine verification failed")
    for r in rows:
        if r.pct >= QUOTA_WARN_PCT:
            warn.append(f"{r.user.username}: {r.pct:.0f}% of quota used")

    if crit:
        return Health("crit", "Attention needed", crit[0], crit + warn)
    if warn:
        return Health("warn", "Check backups", warn[0], warn)
    if not rows:
        return Health("ok", "Ready", "Create a user to start backing up", [])
    return Health("ok", "Healthy", "All systems operational", [])
