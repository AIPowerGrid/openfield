"""Account-isolated staging shell. Public rendering remains a separate gate."""

import json
import os
import re
import stat
import threading
import time
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .app import create_app, index_response
from .auth import SESSION_COOKIE, create_auth_app
from .resources import WorkLimiter, WorkLimits
from .sessions import AccountSessions, SessionError


def _private_directory(path: Path) -> Path:
    path = path.absolute()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Studio workspaces need a private owner-only directory.")
    return path


@dataclass(frozen=True)
class WorkspaceCacheLimits:
    capacity: int = 128
    idle_seconds: float = 900

    def __post_init__(self):
        if type(self.capacity) is not int or not 1 <= self.capacity <= 512:
            raise ValueError("Choose a bounded workspace cache capacity.")
        if (
            type(self.idle_seconds) not in (int, float)
            or not 0 < self.idle_seconds <= 86400
            or not isfinite(self.idle_seconds)
        ):
            raise ValueError("Choose a bounded workspace idle lifetime.")


@dataclass
class WorkspaceEntry:
    workspace_id: str
    app: FastAPI
    last_used: float
    requests: int = 0


@dataclass
class WorkspacePin:
    entry: WorkspaceEntry | None = None
    cancelled: bool = False


class WorkspaceRouter:
    def __init__(
        self,
        accounts: AccountSessions,
        directory: Path,
        host: str,
        limits: WorkLimits | None = None,
        cache: WorkspaceCacheLimits | None = None,
        *,
        clock=time.monotonic,
    ):
        self.accounts = accounts
        self.directory = _private_directory(directory)
        self.host = host
        self.cache = cache or WorkspaceCacheLimits()
        self.clock = clock
        self.limiter = WorkLimiter(
            _private_directory(
                self.directory.parent / ("." + self.directory.name + "-resources")
            ),
            self.directory,
            limits,
        )
        self.apps: dict[str, WorkspaceEntry] = {}
        self.lock = threading.Lock()

    def evictable(self, entry):
        if entry.requests:
            return False
        try:
            return entry.app.state.can_evict() is True and not self.limiter.busy(
                entry.workspace_id
            )
        except (AttributeError, OSError):
            # Unknown activity is not evidence that a workspace is idle.
            return False

    def prune(self, now):
        for key, entry in sorted(self.apps.items(), key=lambda item: item[1].last_used):
            if (
                now - entry.last_used < self.cache.idle_seconds
                and len(self.apps) < self.cache.capacity
            ):
                break
            if self.evictable(entry):
                del self.apps[key]

    def acquire(self, identity, pin=None):
        workspace_id = identity.workspace_id
        if not re.fullmatch(r"[0-9a-f]{32}", workspace_id):
            raise ValueError("Invalid server-owned workspace.")
        with self.lock:
            if pin is not None:
                if pin.cancelled:
                    return None
                if pin.entry is not None:
                    raise RuntimeError("Workspace request already pinned.")
            now = self.clock()
            if workspace_id not in self.apps:
                self.prune(now)
                if len(self.apps) >= self.cache.capacity:
                    return None
                root = _private_directory(self.directory / workspace_id)
                app = create_app(
                    root,
                    "self-hosted",
                    account_host=self.host,
                    inference_enabled=False,
                    work_limiter=self.limiter,
                )
                self.apps[workspace_id] = WorkspaceEntry(workspace_id, app, now)
            entry = self.apps[workspace_id]
            entry.requests += 1
            entry.last_used = now
            if pin is not None:
                pin.entry = entry
            return entry

    def _release(self, entry):
        if self.apps.get(entry.workspace_id) is not entry or entry.requests <= 0:
            raise RuntimeError("Unbalanced workspace request lifetime.")
        entry.requests -= 1
        entry.last_used = self.clock()

    def release(self, entry):
        with self.lock:
            self._release(entry)

    def finish(self, pin):
        with self.lock:
            pin.cancelled = True
            if pin.entry is not None:
                self._release(pin.entry)
                pin.entry = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 4401})
            return
        request = Request(scope, receive=receive)
        unsafe = request.method not in ("GET", "HEAD", "OPTIONS")
        try:
            identity = await run_in_threadpool(
                self.accounts.resolve,
                request.cookies.get(SESSION_COOKIE, ""),
                **(
                    {"csrf": request.headers.get("x-studio-csrf", "")} if unsafe else {}
                ),
            )
        except SessionError:
            response = (
                RedirectResponse("/signin", status_code=303)
                if request.method == "GET" and request.url.path == "/"
                else JSONResponse({"detail": "Sign in to continue."}, status_code=401)
            )
            return await response(scope, receive, send)
        if request.url.path in ("/", "/session.js"):
            state = {**identity.browser_state(), "mode": "hosted"}
            if request.url.path == "/":
                return await index_response(state)(scope, receive, send)
            response = Response(
                "window.studioSession = " + json.dumps(state) + ";",
                media_type="text/javascript",
            )
            return await response(scope, receive, send)
        pin = WorkspacePin()
        try:
            with anyio.CancelScope(shield=True):
                entry = await run_in_threadpool(self.acquire, identity, pin)
            if entry is None:
                response = JSONResponse(
                    {"detail": "Studio staging capacity reached. Try again later."},
                    status_code=503,
                    headers={"Retry-After": "5"},
                )
                return await response(scope, receive, send)
            await entry.app(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.finish, pin)


def create_hosted_app(
    accounts: AccountSessions,
    directory: Path,
    *,
    origin: str,
    google_client_id: str,
    limits: WorkLimits | None = None,
    cache: WorkspaceCacheLimits | None = None,
):
    """Construct private staging, not a deployment command or billing bypass."""
    app = create_auth_app(accounts, origin=origin, google_client_id=google_client_id)
    source = Path(__file__).parent

    @app.get("/health/live")
    async def live():
        return {"status": "alive", "mode": "staging", "rendering": False}

    @app.get("/health/ready")
    async def ready():
        return JSONResponse(
            {"status": "not_ready", "code": "billed_execution_not_enabled"},
            status_code=503,
        )

    @app.get("/signin")
    def signin():
        return FileResponse(source / "signin.html", media_type="text/html")

    @app.get("/signin.js")
    def signin_script():
        return FileResponse(source / "signin.js", media_type="text/javascript")

    @app.get("/signin-mark.svg")
    def signin_mark():
        return FileResponse(
            source / "icons" / "clapperboard.svg", media_type="image/svg+xml"
        )

    app.mount(
        "/",
        WorkspaceRouter(accounts, directory, urlsplit(origin).hostname, limits, cache),
    )
    return app
