"""The iPhone section, served by the iPhone container behind the HydraNest login.

The iPhone container is a modified AirVault (GPL-3.0, see iphone/NOTICE.md)
with its own web UI and API. HydraNest only talks to it over HTTP:

- its web UI is proxied under ``/iphone/app/`` with the iPhone service's
  token added here, so the HydraNest login opens both halves and the UI can
  sit inside the HydraNest layout (same origin, so it may be framed);
- its device list feeds the Overview and Backups pages.
"""

from __future__ import annotations

import datetime as _dt
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from .apple_models import model_name
from .config import Settings
from .overview import STALE_DAYS, Health

log = logging.getLogger("timenest.web.iphone")
# httpx logs every request at INFO, event streams and assets included.
logging.getLogger("httpx").setLevel(logging.WARNING)

PREFIX = "/iphone/app"
CACHE_SECONDS = 15
LIST_TIMEOUT = 3.0

# AirVault's fixed HTTP Basic user (iphone/internal/auth).
_USER = "airvault"
# HydraNest's own session cookie never goes upstream.
_SESSION_COOKIE = "timenest_session"

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
}
_REQUEST_DROP = _HOP_BY_HOP | {"host", "authorization", "cookie"}
# The iPhone UI refuses framing; through HydraNest it is same-origin.
_RESPONSE_DROP = _HOP_BY_HOP | {"x-frame-options"}


@dataclass(slots=True)
class Phone:
    udid: str
    name: str
    model: str | None
    ios: str | None
    connection: str  # wifi | usb | offline
    encrypted: bool
    auto_backup: bool
    last_backup_ts: int | None
    last_seen_ts: int | None
    restore_points: int
    disk_bytes: int | None
    status: str  # ok | running | stale | error | never
    progress: int | None = None

    @property
    def online(self) -> bool:
        return self.connection != "offline"


@dataclass(slots=True)
class PhoneEvent:
    """A phone's latest backup, for the Overview's recent backups."""

    name: str
    udid: str
    ts: int
    status: str  # success | running
    is_phone: bool = True


@dataclass(slots=True)
class Phones:
    configured: bool
    reachable: bool = False
    phones: list[Phone] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(p.disk_bytes or 0 for p in self.phones)

    @property
    def events(self) -> list[PhoneEvent]:
        return [
            PhoneEvent(p.name, p.udid, p.last_backup_ts, "running" if p.status == "running" else "success")
            for p in self.phones if p.last_backup_ts
        ]

    @property
    def restore_points(self) -> int:
        return sum(p.restore_points for p in self.phones)

    def issues(self) -> list[str]:
        if self.configured and not self.reachable:
            return ["iPhone service is not reachable"]
        out: list[str] = []
        for p in self.phones:
            if p.status == "stale":
                out.append(f"{p.name}: no backup for more than {STALE_DAYS} days")
            elif p.status == "error":
                out.append(f"{p.name}: last backup failed")
        return out


_client: httpx.AsyncClient | None = None
_cache: tuple[float, Phones] | None = None


def _http(settings: Settings) -> httpx.AsyncClient:
    global _client
    if _client is None:
        token = settings.iphone_auth_token
        _client = httpx.AsyncClient(
            base_url=(settings.iphone_url or "").rstrip("/"),
            auth=(_USER, token) if token else None,
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Device list for Overview and Backups
# ---------------------------------------------------------------------------

async def phones(settings: Settings) -> Phones:
    """The registered iPhones; cached briefly, since every page view asks."""
    global _cache
    if not settings.iphone_url:
        return Phones(configured=False)
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    try:
        client = _http(settings)
        listed = await client.get("/api/devices", timeout=LIST_TIMEOUT)
        listed.raise_for_status()
        status = await client.get("/api/status", timeout=LIST_TIMEOUT)
        running = {
            r.get("udid"): r
            for r in (status.json().get("running") or [] if status.is_success else [])
            if r.get("kind") == "backup"
        }
        wall = int(time.time())
        result = Phones(
            configured=True,
            reachable=True,
            # Orphaned sources (backups of a removed phone) stay in the iPhone UI.
            phones=[_phone(d, running.get(d.get("udid")), wall)
                    for d in listed.json().get("devices") or [] if not d.get("orphaned")],
        )
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("iPhone service not reachable at %s: %s", settings.iphone_url, exc)
        result = Phones(configured=True)
    _cache = (now, result)
    return result


def _ts(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return int(_dt.datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def _phone(d: dict[str, Any], run: dict[str, Any] | None, now: int) -> Phone:
    last = _ts(d.get("lastBackup"))
    if run:
        status = "running"
    elif (d.get("lastRunErrors") or {}).get("backup"):
        status = "error"
    elif not last:
        status = "never"
    elif now - last > STALE_DAYS * 86400:
        status = "stale"
    else:
        status = "ok"
    return Phone(
        udid=str(d.get("udid", "")),
        name=str(d.get("name") or d.get("udid") or "iPhone"),
        model=model_name(d.get("productType")),
        ios=d.get("iosVersion"),
        connection=str(d.get("connection") or "offline"),
        encrypted=bool(d.get("encrypted")),
        auto_backup=bool((d.get("autoBackup") or {}).get("enabled")),
        last_backup_ts=last,
        last_seen_ts=_ts(d.get("lastSeen")),
        restore_points=int(d.get("restorePoints") or 0),
        disk_bytes=d.get("diskBytes"),
        status=status,
        progress=run.get("progress") if run else None,
    )


def with_issues(health: Health, phones: Phones) -> Health:
    """The Overview health with the iPhones' problems added."""
    issues = phones.issues()
    if not issues:
        return health
    if health.level == "crit":
        return Health("crit", health.title, health.detail, health.issues + issues)
    if health.level == "warn":
        return Health("warn", health.title, health.detail, health.issues + issues)
    return Health("warn", "Check backups", issues[0], issues)


# ---------------------------------------------------------------------------
# Proxy for the iPhone web UI and API
# ---------------------------------------------------------------------------

def _cookies(header: str | None) -> str | None:
    if not header:
        return None
    kept = [c.strip() for c in header.split(";")
            if c.strip() and c.split("=", 1)[0].strip() != _SESSION_COOKIE]
    return "; ".join(kept) or None


async def _relay(upstream: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()


def unauthenticated(rest: str) -> Response:
    """The HydraNest session is gone: the API says so, a page sends the whole
    window (not just the frame) to the HydraNest login."""
    if rest.startswith("/api/"):
        return JSONResponse({"code": "authentication_required"}, status_code=401)
    return HTMLResponse("<script>window.top.location.href = '/login';</script>", status_code=401)


async def proxy(request: Request, settings: Settings) -> Response:
    raw: bytes = request.scope.get("raw_path") or request.url.path.encode()
    rest = raw[len(PREFIX):].decode("latin-1") or "/"
    if request.url.query:
        rest += "?" + request.url.query

    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _REQUEST_DROP]
    cookie = _cookies(request.headers.get("cookie"))
    if cookie:
        headers.append(("cookie", cookie))
    has_body = "content-length" in request.headers or "transfer-encoding" in request.headers

    client = _http(settings)
    outgoing = client.build_request(
        request.method, rest, headers=headers,
        content=request.stream() if has_body else None,
        # Event streams, downloads and uploads run as long as they need.
        timeout=httpx.Timeout(None, connect=5.0),
    )
    try:
        upstream = await client.send(outgoing, stream=True)
    except httpx.HTTPError as exc:
        log.warning("iPhone proxy: %s %s: %s", request.method, rest, exc)
        return Response(
            "The iPhone service is not reachable. Check IPHONE_URL and that the iphone container is running.",
            status_code=502, media_type="text/plain",
        )

    response = StreamingResponse(
        _relay(upstream), status_code=upstream.status_code,
        background=BackgroundTask(upstream.aclose),
    )
    for key, value in upstream.headers.multi_items():
        if key.lower() not in _RESPONSE_DROP:
            response.headers.append(key, value)
    response.headers["x-frame-options"] = "SAMEORIGIN"
    return response
