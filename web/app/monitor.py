"""Background poller for live SMB state.

Every POLL_SECONDS it asks Samba for the active sessions and remembers, per
user, when and from where a Mac was last connected. smbstatus only knows
about *current* sessions, so this history is what lets the UI say "last seen
3h ago" for Macs that are asleep or away. It is persisted as JSON under the
web data dir so it survives container restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .samba_mgr import SambaManager, SmbSession

log = logging.getLogger(__name__)

POLL_SECONDS = 60


@dataclass(slots=True)
class ClientSeen:
    user: str
    ip: str
    hostname: str | None
    last_seen_ts: int
    protocol: str


@dataclass(slots=True)
class LiveState:
    samba_ok: bool = True
    checked_ts: int = 0
    sessions: list[SmbSession] = field(default_factory=list)
    seen: dict[str, ClientSeen] = field(default_factory=dict)


class Monitor:
    def __init__(self, mgr_factory: Callable[[], SambaManager], data_dir: Path) -> None:
        self._mgr_factory = mgr_factory
        self._file = data_dir / "clients.json"
        self.state = LiveState(seen=self._load())
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._hostnames: dict[str, str | None] = {}

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 - never let the poller die
                log.exception("monitor refresh failed")
            await asyncio.sleep(POLL_SECONDS)

    # ------------------------------------------------------------- polling

    async def refresh(self) -> LiveState:
        async with self._lock:
            mgr = self._mgr_factory()
            now = int(time.time())
            try:
                sessions = await mgr.list_sessions()
                self.state.samba_ok = True
            except RuntimeError as exc:
                log.warning("samba unreachable: %s", exc)
                sessions = []
                self.state.samba_ok = False
            self.state.sessions = sessions
            self.state.checked_ts = now
            for s in sessions:
                self.state.seen[s.user] = ClientSeen(
                    user=s.user,
                    ip=s.ip,
                    hostname=await self._hostname(s.ip),
                    last_seen_ts=now,
                    protocol=s.protocol,
                )
            if sessions:
                self._save()
            return self.state

    async def current(self, max_age: int = 20) -> LiveState:
        """State no older than max_age seconds (refreshes on demand)."""
        if int(time.time()) - self.state.checked_ts > max_age:
            await self.refresh()
        return self.state

    async def _hostname(self, ip: str) -> str | None:
        if not ip or ip in ("127.0.0.1", "::1"):
            return None
        if ip not in self._hostnames:
            loop = asyncio.get_running_loop()
            try:
                name = await asyncio.wait_for(
                    loop.run_in_executor(None, socket.gethostbyaddr, ip), timeout=2
                )
                self._hostnames[ip] = name[0].split(".")[0]
            except (OSError, asyncio.TimeoutError):
                self._hostnames[ip] = None
        return self._hostnames[ip]

    # --------------------------------------------------------- persistence

    def _load(self) -> dict[str, ClientSeen]:
        try:
            raw = json.loads(self._file.read_text())
            return {k: ClientSeen(**v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: asdict(v) for k, v in self.state.seen.items()}))
            tmp.replace(self._file)
        except OSError as exc:
            log.warning("could not persist %s: %s", self._file, exc)
