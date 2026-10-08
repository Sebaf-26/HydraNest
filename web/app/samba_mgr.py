"""Thin wrapper around the Samba container.

We shell out to ``docker exec`` rather than re-implementing Samba's
passdb protocol because tdbsam is version-sensitive and a plain shell
call is trivially auditable. The helper scripts in ./scripts/ do the
actual work inside the container.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import timemachine
from .config import Settings

log = logging.getLogger(__name__)


_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SESSIONS_RE = re.compile(
    r"^(?P<pid>\d+)\s+(?P<user>\S+)\s+(?P<group>\S+)\s+"
    r"(?P<machine>\S+)\s+\((?P<ip>[^)]+)\)\s+(?P<proto>\S+)",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class TimeNestUser:
    username: str
    quota_gb: int
    path: Path
    used_bytes: int
    last_backup_ts: int | None


@dataclass(frozen=True, slots=True)
class SmbSession:
    pid: int
    user: str
    machine: str
    ip: str
    protocol: str
    connected_ts: int | None = None
    encrypted: bool = False


class SambaManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ users

    async def create_user(self, username: str, password: str, quota_gb: int) -> None:
        self._validate_username(username)
        if quota_gb < 10:
            raise ValueError("quota must be at least 10 GB")
        await self._exec(
            "/usr/local/bin/create-user.sh",
            username,
            password,
            str(quota_gb),
        )

    async def delete_user(self, username: str, purge: bool = False) -> None:
        self._validate_username(username)
        args = ["/usr/local/bin/delete-user.sh", username]
        if purge:
            args.append("--purge")
        await self._exec(*args)

    async def update_user(
        self, username: str, quota_gb: int, password: str | None = None
    ) -> None:
        self._validate_username(username)
        if quota_gb < 10:
            raise ValueError("quota must be at least 10 GB")
        if password:
            # create-user.sh is idempotent: rotates the password and rewrites
            # the share fragment with the new quota.
            await self.create_user(username, password, quota_gb)
        else:
            await self._exec("/usr/local/bin/set-quota.sh", username, str(quota_gb))

    def list_users(self) -> list[TimeNestUser]:
        # Keep resolution loose: explicit SHARES_PATH first, then the layouts
        # older stacks used.
        for candidate in (
            self.settings.shares_path,
            (self.settings.samba_data_path / ".." / "config" / "shares.d").resolve(),
            Path("/etc/timenest/shares.d"),
            Path("/config/shares.d"),
            Path("/data/config/shares.d"),
        ):
            if candidate.is_dir():
                shares_dir = candidate
                break
        else:
            log.warning(
                "no shares.d directory found (SHARES_PATH=%s); mount the samba "
                "container's shares.d into the web container",
                self.settings.shares_path,
            )
            return []

        users: list[TimeNestUser] = []
        for conf in shares_dir.glob("*.conf"):
            username = conf.stem
            quota = self._parse_quota(conf)
            user_dir = self.settings.backup_path / username
            scan = timemachine.scan_user(user_dir)
            users.append(
                TimeNestUser(
                    username=username,
                    quota_gb=quota,
                    path=user_dir,
                    used_bytes=scan.size_bytes,
                    last_backup_ts=scan.last_backup_ts,
                )
            )
        users.sort(key=lambda u: u.username)
        return users

    # --------------------------------------------------------------- sessions

    async def list_sessions_safe(self) -> list[SmbSession]:
        try:
            return await self.list_sessions()
        except RuntimeError as exc:
            log.warning("smbstatus failed: %s", exc)
            return []

    async def list_sessions(self) -> list[SmbSession]:
        """Active SMB sessions. Raises RuntimeError if Samba is unreachable."""
        try:
            out = await self._exec("smbstatus", "--json")
            return _parse_sessions_json(out)
        except (RuntimeError, ValueError) as exc:
            log.debug("smbstatus --json unavailable (%s), falling back", exc)
        out = await self._exec("smbstatus", "-b")
        return [
            SmbSession(
                pid=int(m["pid"]),
                user=m["user"],
                machine=m["machine"],
                ip=m["ip"],
                protocol=m["proto"],
            )
            for m in _SESSIONS_RE.finditer(out)
        ]

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _validate_username(username: str) -> None:
        if not _USERNAME_RE.match(username):
            raise ValueError(
                "username must match [a-z_][a-z0-9_-]{0,31}"
            )

    @staticmethod
    def _parse_quota(conf: Path) -> int:
        try:
            for line in conf.read_text().splitlines():
                key, _, val = line.strip().partition("=")
                if key.strip() == "fruit:time machine max size":
                    return int(val.strip().rstrip("Gg"))
        except OSError:
            pass
        return 0

    async def _exec(self, *args: str) -> str:
        cmd = [
            "docker",
            "exec",
            "-i",
            self.settings.samba_container,
            *args,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            # Translate "docker CLI missing" into RuntimeError so callers
            # that already catch RuntimeError (list_sessions) degrade
            # gracefully instead of returning a 500 to the browser.
            raise RuntimeError(
                f"{cmd[0]} not found in PATH; install docker CLI or mount "
                f"the host binary into the web container"
            ) from exc
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"{' '.join(cmd[:4])} failed ({proc.returncode}): "
                f"{stderr.decode().strip() or stdout.decode().strip()}"
            )
        return stdout.decode()


def _parse_sessions_json(out: str) -> list[SmbSession]:
    data = json.loads(out)
    connected: dict[str, int] = {}
    for tcon in (data.get("tcons") or {}).values():
        sid = str(tcon.get("session_id", ""))
        ts = _iso_ts(tcon.get("connected_at"))
        if sid and ts and (sid not in connected or ts < connected[sid]):
            connected[sid] = ts
    sessions = []
    for sid, sess in (data.get("sessions") or {}).items():
        user = sess.get("username") or ""
        if not user or user in ("nobody", "-1"):
            continue
        enc = (sess.get("encryption") or {}).get("degree", "none")
        sessions.append(
            SmbSession(
                pid=int((sess.get("server_id") or {}).get("pid", 0) or 0),
                user=user,
                machine=sess.get("remote_machine") or "",
                ip=sess.get("remote_machine") or "",
                protocol=sess.get("session_dialect") or "",
                connected_ts=connected.get(str(sid)),
                encrypted=enc not in ("none", "", None),
            )
        )
    return sessions


def _iso_ts(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(dt.datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None
