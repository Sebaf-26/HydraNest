"""FastAPI entrypoint for the HydraNest web UI."""

from __future__ import annotations

import datetime as _dt
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, disks, metrics, overview, samba_mgr, timemachine
from .monitor import Monitor
from .auth import LoginDep, verify_login
from .config import Settings, get_settings

# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------
settings = get_settings()


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    monitor.start()
    yield
    await monitor.stop()


app = FastAPI(title="HydraNest", docs_url=None, redoc_url=None, lifespan=_lifespan)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("timenest.web")

# Session secret persists across restarts so users don't get logged out on
# container updates. Generated once and stashed alongside the data volume.
session_secret = settings.session_secret
if not session_secret:
    secret_file = settings.data_dir / ".session_secret"
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if secret_file.exists():
            session_secret = secret_file.read_text().strip()
        else:
            session_secret = secrets.token_urlsafe(64)
            secret_file.write_text(session_secret)
            secret_file.chmod(0o600)
    except OSError:
        session_secret = secrets.token_urlsafe(64)

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="timenest_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=False,  # reverse proxy handles TLS; flip to True behind https
)

_static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

_templates_dir = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)
templates.env.globals["version"] = __version__
templates.env.globals["server_name"] = settings.admin_user


def _mgr() -> samba_mgr.SambaManager:
    return samba_mgr.SambaManager(settings)


monitor = Monitor(_mgr, settings.data_dir)


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024  # type: ignore[assignment]
    return f"{n} PB"


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return "never"
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _fmt_ago(ts: int | None) -> str:
    if not ts:
        return "never"
    delta = int(time.time()) - ts
    if delta < 60:
        return "just now"
    for size, unit in ((86400 * 30, "mo"), (86400, "d"), (3600, "h"), (60, "m")):
        if delta >= size:
            return f"{delta // size}{unit} ago"
    return "just now"


def _fmt_when(ts: int | None) -> str:
    """'Today, 10:42' / 'Yesterday, 22:10' / '3 Oct, 09:15'."""
    if not ts:
        return "-"
    d = _dt.datetime.fromtimestamp(ts)
    today = _dt.date.today()
    if d.date() == today:
        return f"Today, {d:%H:%M}"
    if d.date() == today - _dt.timedelta(days=1):
        return f"Yesterday, {d:%H:%M}"
    return f"{d.day} {d:%b}, {d:%H:%M}"


templates.env.filters["bytes"] = _fmt_bytes
templates.env.filters["ts"] = _fmt_ts
templates.env.filters["ago"] = _fmt_ago
templates.env.filters["when"] = _fmt_when


async def _render(request: Request, template: str, page: str, **ctx: Any) -> Response:
    live = await monitor.current()
    return templates.TemplateResponse(
        template,
        {"request": request, "page": page, "samba_ok": live.samba_ok, **ctx},
    )


async def _overview() -> overview.Overview:
    live = await monitor.current()
    return overview.build(settings, _mgr().list_users(), live)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    if request.session.get("user"):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    cfg: Settings = Depends(get_settings),
) -> Response:
    if not verify_login(username, password, cfg):
        log.warning("failed login for '%s' from %s", username, request.client.host if request.client else "?")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session["user"] = username
    log.info("login ok: %s", username)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse)
async def overview_page(request: Request, user: str = LoginDep) -> Response:
    return await _render(request, "overview.html", "overview", ov=await _overview())


@app.get("/backups", response_class=HTMLResponse)
async def backups_page(request: Request, user: str = LoginDep) -> Response:
    return await _render(request, "backups.html", "backups", ov=await _overview())


@app.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request, user: str = LoginDep) -> Response:
    return await _render(request, "clients.html", "clients", ov=await _overview())


@app.get("/quotas", response_class=HTMLResponse)
async def quotas_page(request: Request, user: str = LoginDep) -> Response:
    return await _render(
        request,
        "quotas.html",
        "quotas",
        ov=await _overview(),
        updated=request.query_params.get("updated"),
        error=request.query_params.get("error"),
    )


@app.post("/quotas/{username}")
async def quotas_update(
    username: str,
    quota_gb: int = Form(...),
    user: str = LoginDep,
) -> Response:
    try:
        await _mgr().update_user(username, quota_gb)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(f"/quotas?error={exc}", status_code=status.HTTP_303_SEE_OTHER)
    log.info("updated quota of '%s' to %d GB", username, quota_gb)
    return RedirectResponse(f"/quotas?updated={username}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/refresh")
async def refresh(request: Request, user: str = LoginDep) -> Response:
    timemachine.invalidate()
    await monitor.refresh()
    back = request.headers.get("referer") or "/"
    return RedirectResponse(back, status_code=status.HTTP_303_SEE_OTHER)


@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, user: str = LoginDep) -> Response:
    return await _render(
        request,
        "users.html",
        "users",
        users=_mgr().list_users(),
        default_quota_gb=settings.default_quota_gb,
        created=request.query_params.get("created"),
        deleted=request.query_params.get("deleted"),
        updated=request.query_params.get("updated"),
        error=request.query_params.get("error"),
    )


@app.post("/users")
async def users_create(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    quota_gb: int = Form(...),
    user: str = LoginDep,
) -> Response:
    try:
        await _mgr().create_user(username, password, quota_gb)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(
            f"/users?error={exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    log.info("created user '%s' (%d GB quota)", username, quota_gb)
    return RedirectResponse(
        f"/users?created={username}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/users/{username}/update")
async def users_update(
    username: str,
    quota_gb: int = Form(...),
    password: str = Form(default=""),
    user: str = LoginDep,
) -> Response:
    if password and len(password) < 8:
        return RedirectResponse(
            "/users?error=password must be at least 8 characters",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    try:
        await _mgr().update_user(username, quota_gb, password or None)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(
            f"/users?error={exc}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    log.info(
        "updated user '%s' (%d GB quota, password %s)",
        username,
        quota_gb,
        "changed" if password else "unchanged",
    )
    return RedirectResponse(
        f"/users?updated={username}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/users/{username}/delete")
async def users_delete(
    username: str,
    purge: str = Form(default=""),
    user: str = LoginDep,
) -> Response:
    try:
        await _mgr().delete_user(username, purge=bool(purge))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    log.info("deleted user '%s' (purge=%s)", username, bool(purge))
    return RedirectResponse(
        f"/users?deleted={username}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/disks", response_class=HTMLResponse)
async def disks_page(request: Request, user: str = LoginDep) -> Response:
    du = disks.usage(settings.backup_path)
    # Probe common device paths. Missing devices simply show "unavailable".
    smart_results = []
    for dev in _probe_devices():
        status_ = await disks.smart(dev)
        if status_:
            smart_results.append(status_)
    return await _render(
        request,
        "disks.html",
        "disks",
        disk=du,
        smart=smart_results,
        backup_path=str(settings.backup_path),
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: str = LoginDep) -> Response:
    return await _render(
        request,
        "settings.html",
        "settings",
        settings={
            "admin_user": settings.admin_user,
            "backup_path": str(settings.backup_path),
            "default_quota_gb": settings.default_quota_gb,
            "log_level": settings.log_level,
            "timezone": settings.timezone,
            "enable_metrics": settings.enable_metrics,
        },
    )


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    if not settings.enable_metrics:
        raise HTTPException(404, "metrics disabled")
    body = await metrics.render(settings, _mgr())
    return Response(body, media_type=metrics.CONTENT_TYPE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe_devices() -> list[str]:
    """Enumerate likely disk device nodes in a sensible order.

    On Raspberry Pi the backup drive is typically /dev/sda; on NUCs and
    generic Linux boxes it is /dev/sdb; on Mac mini we skip because the
    container cannot read raw disk devices through Docker Desktop.
    """
    import os
    candidates = []
    for p in ("/dev/sda", "/dev/sdb", "/dev/sdc", "/dev/nvme0n1", "/dev/nvme1n1"):
        if os.path.exists(p):
            candidates.append(p)
    return candidates
