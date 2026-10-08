"""Read-only inspection of Time Machine backup bundles.

A network Time Machine destination looks like::

    /backup/<user>/<Computer Name>.sparsebundle/      (or .backupbundle)
        com.apple.TimeMachine.MachineID.plist      model, host UUID, verification
        com.apple.TimeMachine.SnapshotHistory.plist  completed snapshots (APFS)
        bands/                                     the actual disk image data

Everything here is best effort: a bundle that is being written, an older
HFS+ backup without SnapshotHistory, or a plist with unexpected keys must
never break a page, so every parser falls back to "unknown".

Walking `bands/` of a large backup touches tens of thousands of files, so
results are cached for CACHE_TTL seconds.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import plistlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CACHE_TTL = 120
BUNDLE_SUFFIXES = (".sparsebundle", ".backupbundle")


@dataclass(frozen=True, slots=True)
class Snapshot:
    name: str
    completed_ts: int
    bytes_copied: int | None


@dataclass(frozen=True, slots=True)
class Bundle:
    user: str
    mac_name: str
    path: Path
    size_bytes: int
    last_activity_ts: int | None
    model_id: str | None
    host_uuid: str | None
    verification: str | None
    snapshots: tuple[Snapshot, ...] = field(default_factory=tuple)

    @property
    def last_snapshot(self) -> Snapshot | None:
        return self.snapshots[0] if self.snapshots else None

    @property
    def last_backup_ts(self) -> int | None:
        if self.snapshots:
            return self.snapshots[0].completed_ts
        return self.last_activity_ts

    @property
    def model_name(self) -> str:
        return model_name(self.model_id)

    @property
    def is_laptop(self) -> bool:
        return (self.model_id or "").startswith("MacBook")


@dataclass(frozen=True, slots=True)
class UserScan:
    size_bytes: int
    last_activity_ts: int | None
    bundles: tuple[Bundle, ...]

    @property
    def last_backup_ts(self) -> int | None:
        stamps = [b.last_backup_ts for b in self.bundles if b.last_backup_ts]
        if stamps:
            return max(stamps)
        return self.last_activity_ts


_cache: dict[Path, tuple[float, UserScan]] = {}


def scan_user(user_dir: Path, *, fresh: bool = False) -> UserScan:
    now = time.monotonic()
    hit = _cache.get(user_dir)
    if hit and not fresh and now - hit[0] < CACHE_TTL:
        return hit[1]
    result = _scan_user(user_dir)
    _cache[user_dir] = (now, result)
    return result


def invalidate(user_dir: Path | None = None) -> None:
    if user_dir is None:
        _cache.clear()
    else:
        _cache.pop(user_dir, None)


def _scan_user(user_dir: Path) -> UserScan:
    if not user_dir.is_dir():
        return UserScan(0, None, ())
    total, newest = _walk(user_dir)
    bundles: list[Bundle] = []
    try:
        entries = list(os.scandir(user_dir))
    except OSError:
        entries = []
    for entry in entries:
        if entry.is_dir(follow_symlinks=False) and entry.name.endswith(BUNDLE_SUFFIXES):
            bundles.append(_read_bundle(user_dir.name, Path(entry.path)))
    bundles.sort(key=lambda b: b.last_backup_ts or 0, reverse=True)
    return UserScan(total, newest, tuple(bundles))


def _read_bundle(user: str, path: Path) -> Bundle:
    size, newest = _walk(path)
    machine = _load_plist(path / "com.apple.TimeMachine.MachineID.plist")
    history = _load_plist(path / "com.apple.TimeMachine.SnapshotHistory.plist")
    mac_name = path.name
    for suffix in BUNDLE_SUFFIXES:
        if mac_name.endswith(suffix):
            mac_name = mac_name[: -len(suffix)]
    return Bundle(
        user=user,
        mac_name=mac_name,
        path=path,
        size_bytes=size,
        last_activity_ts=newest,
        model_id=_str(machine.get("com.apple.backupd.ModelID")),
        host_uuid=_str(machine.get("com.apple.backupd.HostUUID")),
        verification=_verification(machine.get("VerificationState")),
        snapshots=_snapshots(history),
    )


def _walk(root: Path) -> tuple[int, int | None]:
    """Total size and newest mtime below root, without following symlinks."""
    total = 0
    newest = 0.0
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    newest = max(newest, st.st_mtime)
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        total += st.st_size
        except OSError:
            continue
    return total, (int(newest) if newest else None)


def _load_plist(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            data = plistlib.load(fh)
    except Exception:  # noqa: BLE001 - any unreadable/partial plist means "unknown"
        return {}
    return data if isinstance(data, dict) else {}


def _snapshots(history: dict[str, Any]) -> tuple[Snapshot, ...]:
    raw = history.get("Snapshots")
    if not isinstance(raw, list):
        return ()
    out: list[Snapshot] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        completed: dt.datetime | None = None
        name = ""
        copied: int | None = None
        for key, value in item.items():
            lk = key.lower()
            if isinstance(value, dt.datetime) and "completion" in lk:
                completed = value
            elif isinstance(value, dt.datetime) and completed is None and "date" in lk:
                completed = value
            elif isinstance(value, str) and lk.endswith("snapshotname"):
                name = value
            elif isinstance(value, int) and "bytes" in lk and "copied" in lk:
                copied = value
        if completed is None and name:
            completed = _date_from_name(name)
        if completed is None:
            continue
        if completed.tzinfo is None:
            completed = completed.replace(tzinfo=dt.timezone.utc)
        out.append(Snapshot(name=name, completed_ts=int(completed.timestamp()), bytes_copied=copied))
    out.sort(key=lambda s: s.completed_ts, reverse=True)
    return tuple(out)


_NAME_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})")


def _date_from_name(name: str) -> dt.datetime | None:
    m = _NAME_DATE_RE.search(name)
    if not m:
        return None
    try:
        y, mo, d, h, mi, sec = (int(g) for g in m.groups())
        return dt.datetime(y, mo, d, h, mi, sec)
    except ValueError:
        return None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _verification(value: Any) -> str | None:
    # 1 = verified OK, 2 = verification failed / needs a new backup.
    if value == 1:
        return "verified"
    if value == 2:
        return "failed"
    if isinstance(value, int):
        return "unknown"
    return None


_MODEL_NAMES = (
    ("MacBookPro", "MacBook Pro"),
    ("MacBookAir", "MacBook Air"),
    ("MacBook", "MacBook"),
    ("iMacPro", "iMac Pro"),
    ("iMac", "iMac"),
    ("Macmini", "Mac mini"),
    ("MacPro", "Mac Pro"),
)


def model_name(model_id: str | None) -> str:
    if not model_id:
        return "Mac"
    for prefix, label in _MODEL_NAMES:
        if model_id.startswith(prefix):
            return label
    # Apple-silicon era IDs ("Mac14,3") don't say which product they are.
    return "Mac"
