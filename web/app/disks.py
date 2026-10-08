"""Backup volume usage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import psutil

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiskUsage:
    mount: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


def usage(mount: Path | str) -> DiskUsage | None:
    try:
        s = psutil.disk_usage(str(mount))
    except (FileNotFoundError, PermissionError):
        return None
    return DiskUsage(
        mount=str(mount),
        total_bytes=s.total,
        used_bytes=s.used,
        free_bytes=s.free,
        percent=s.percent,
    )
