"""Bound request ingestion and admit expensive staging work without queuing it."""

import json
import re
import shutil
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import anyio
from fastapi import HTTPException
from filelock import FileLock, Timeout
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from .project import atomic_json
from .transfer_limits import EXPORT_PEAK_BYTES, IMPORT_PEAK_BYTES, MAX_ARCHIVE_BYTES

MIB = 1024 * 1024


def body_limit(scope) -> int:
    path = scope["path"]
    if path.startswith("/auth/"):
        return 48 * 1024
    if scope["method"] == "POST":
        if path in {"/api/sources", "/api/audio", "/api/looks"}:
            return {"/api/sources": 101, "/api/audio": 51, "/api/looks": 13}[path] * MIB
        if re.fullmatch(r"/api/project-imports/[0-9a-f]{32}", path):
            return MAX_ARCHIVE_BYTES
    return 2 * MIB


class RequestLimitsMiddleware:
    def __init__(self, app, *, idle_seconds=30, body_seconds=180, clock=None):
        self.app = app
        self.idle_seconds = idle_seconds
        self.body_seconds = body_seconds
        self.clock = clock or anyio.current_time

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        failure = None
        started = False
        replaced = False

        async def private_send(message):
            nonlocal started, replaced
            if message["type"] == "http.response.start":
                started = True
                if failure:
                    # BaseHTTPMiddleware can group receive errors, which FastAPI
                    # otherwise turns into a generic parsing error.
                    response = JSONResponse(
                        {"detail": failure.detail}, status_code=failure.status_code
                    )
                    message = {
                        **message,
                        "status": response.status_code,
                        "headers": response.raw_headers,
                    }
                headers = MutableHeaders(scope=message)
                for name, value in {
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer",
                    "X-Frame-Options": "DENY",
                    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
                }.items():
                    headers.setdefault(name, value)
            elif message["type"] == "http.response.body" and failure:
                if replaced:
                    return
                replaced = True
                message = {
                    "type": "http.response.body",
                    "body": JSONResponse({"detail": failure.detail}).body,
                }
            await send(message)

        lengths = [value for key, value in scope["headers"] if key == b"content-length"]
        if len(lengths) > 1 or any(
            not value or not value.isdigit() or len(value) > 20 for value in lengths
        ):
            return await JSONResponse(
                {"detail": "Invalid request size."}, status_code=400
            )(scope, receive, private_send)
        maximum = body_limit(scope)
        if lengths and int(lengths[0]) > maximum:
            return await JSONResponse(
                {"detail": "This upload or request is too large."}, status_code=413
            )(scope, receive, private_send)
        deadline = self.clock() + self.body_seconds
        received = 0

        async def bounded_receive():
            nonlocal received, failure
            try:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError
                with anyio.fail_after(min(self.idle_seconds, remaining)):
                    message = await receive()
                if self.clock() > deadline:
                    raise TimeoutError
            except TimeoutError as error:
                failure = HTTPException(408, "Upload timed out. Choose the file again.")
                raise failure from error
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    failure = HTTPException(413, "This upload or request is too large.")
                    raise failure
            return message

        try:
            await self.app(scope, bounded_receive, private_send)
        except Exception:
            if not failure:
                raise
            if started:
                if replaced:
                    return
                raise
            await JSONResponse(
                {"detail": failure.detail}, status_code=failure.status_code
            )(scope, receive, private_send)


@dataclass(frozen=True)
class WorkLimits:
    concurrent: int = 4
    per_workspace: int = 2
    minimum_free_bytes: int = 2 * 1024**3
    workspace_bytes: int = 8 * 1024**3
    total_bytes: int = 128 * 1024**3
    scan_entries: int = 100000

    def __post_init__(self):
        values = asdict(self)
        if any(type(value) is not int for value in values.values()):
            raise ValueError("Resource limits must be whole numbers.")
        if not 1 <= self.per_workspace <= self.concurrent <= 64:
            raise ValueError("Choose bounded workspace/global work concurrency.")
        if (
            self.minimum_free_bytes < 0
            or not 1 <= self.workspace_bytes <= self.total_bytes
            or not 1 <= self.scan_entries <= 1000000
        ):
            raise ValueError("Choose bounded storage admission limits.")


class ResourceError(Exception):
    def __init__(self, detail: str, status: int = 429):
        super().__init__(detail)
        self.status = status


def below_storage_limit(root: Path, maximum: int, entries: int) -> bool:
    """Count apparent file bytes conservatively; never follow account symlinks."""
    import os

    if maximum <= 0:
        return False
    count, size, pending = 0, 0, [root]
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                count += 1
                if count > entries or child.is_symlink():
                    return False
                if child.is_dir(follow_symlinks=False):
                    pending.append(Path(child.path))
                elif child.is_file(follow_symlinks=False):
                    size += child.stat(follow_symlinks=False).st_size
                    if size >= maximum:
                        return False
                else:
                    return False
    return True


class WorkLimiter:
    def __init__(self, root: Path, workspaces: Path, limits: WorkLimits | None = None):
        self.root, self.workspaces = root.resolve(), workspaces.resolve()
        self.limits = limits or WorkLimits()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with FileLock(self.root / ".policy.lock", mode=0o600):
            policy = self.root / "policy.json"
            expected = {
                "workspaces": str(self.workspaces),
                "limits": asdict(self.limits),
                "transfer_peak_bytes": {
                    "import": IMPORT_PEAK_BYTES,
                    "package": EXPORT_PEAK_BYTES,
                },
            }
            if policy.exists():
                import json

                if json.loads(policy.read_text()) != expected:
                    raise ValueError("Resource policy differs from the running store.")
            else:
                atomic_json(policy, expected)

    @classmethod
    def reopen(cls, root: Path):
        import json

        policy = json.loads((root / "policy.json").read_text())
        return cls(root, Path(policy["workspaces"]), WorkLimits(**policy["limits"]))

    def _slot(self, stack, prefix, count):
        for index in range(count):
            slot = FileLock(
                self.root / f"{prefix}-{index}.lock", mode=0o600, thread_local=False
            )
            try:
                slot.acquire(timeout=0)
            except Timeout:
                continue
            stack.callback(slot.release)
            return index
        raise ResourceError("Studio is busy. Wait for current work, then try again.")

    def _reserved(self, workspace_id, own_slot):
        total, workspace = 0, 0
        for index in range(self.limits.concurrent):
            if index == own_slot:
                continue
            probe = FileLock(
                self.root / f"global-{index}.lock", mode=0o600, thread_local=False
            )
            try:
                probe.acquire(timeout=0)
            except Timeout:
                record = self.root / f"reservation-{index}.json"
                try:
                    if record.is_symlink() or record.stat().st_size > 4096:
                        raise ValueError
                    data = json.loads(record.read_text())
                    if (
                        not isinstance(data, dict)
                        or set(data) != {"workspace_id", "bytes"}
                        or not isinstance(data["workspace_id"], str)
                        or not re.fullmatch(r"[0-9a-f]{32}", data["workspace_id"])
                        or type(data["bytes"]) is not int
                        or not 0 <= data["bytes"] <= 2**63 - 1
                    ):
                        raise ValueError
                except (OSError, ValueError) as error:
                    raise ResourceError(
                        "Studio storage capacity is unavailable. Try again later.", 503
                    ) from error
                total += data["bytes"]
                if data["workspace_id"] == workspace_id:
                    workspace += data["bytes"]
            else:
                # An unheld slot's record is stale, including after process death.
                probe.release()
        return workspace, total

    def busy(self, workspace_id: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{32}", workspace_id):
            raise ValueError("Invalid server-owned workspace.")
        for prefix, count in (
            ("workspace-" + workspace_id, self.limits.per_workspace),
            ("export-" + workspace_id, 1),
        ):
            for index in range(count):
                probe = FileLock(
                    self.root / f"{prefix}-{index}.lock", mode=0o600, thread_local=False
                )
                try:
                    probe.acquire(timeout=0)
                except Timeout:
                    return True
                else:
                    probe.release()
        return False

    @contextmanager
    def acquire(
        self,
        workspace_id: str,
        *,
        export: bool = False,
        reserve_bytes: int = 0,
        check_spool: bool = True,
    ):
        if not re.fullmatch(r"[0-9a-f]{32}", workspace_id):
            raise ValueError("Invalid server-owned workspace.")
        if type(reserve_bytes) is not int or not 0 <= reserve_bytes <= 2**63 - 1:
            raise ValueError("Reserve a bounded whole number of work bytes.")
        if type(check_spool) is not bool:
            raise ValueError("Spool admission must be a server-owned boolean.")
        workspace = self.workspaces / workspace_id
        if not workspace.is_dir() or workspace.is_symlink():
            raise ValueError("Workspace storage is unavailable.")
        with ExitStack() as stack:
            if export:
                self._slot(stack, "export-" + workspace_id, 1)
            self._slot(stack, "workspace-" + workspace_id, self.limits.per_workspace)
            try:
                # Claim the slot and its planned storage bytes under one lock.
                # Records are authoritative only while their process holds a slot.
                with FileLock(self.root / ".storage.lock", mode=0o600, timeout=5):
                    index = self._slot(stack, "global", self.limits.concurrent)
                    pending_workspace, pending_total = self._reserved(
                        workspace_id, index
                    )
                    required_free = (
                        self.limits.minimum_free_bytes + pending_total + reserve_bytes
                    )
                    admitted = (
                        shutil.disk_usage(self.workspaces).free >= required_free
                        and (
                            not reserve_bytes
                            or not check_spool
                            or shutil.disk_usage(tempfile.gettempdir()).free
                            >= required_free
                        )
                        and below_storage_limit(
                            workspace,
                            self.limits.workspace_bytes
                            - pending_workspace
                            - reserve_bytes,
                            self.limits.scan_entries,
                        )
                        and below_storage_limit(
                            self.workspaces,
                            self.limits.total_bytes - pending_total - reserve_bytes,
                            self.limits.scan_entries,
                        )
                    )
                    if not admitted:
                        raise ResourceError(
                            "Studio storage is full. Existing projects remain available.",
                            507,
                        )
                    atomic_json(
                        self.root / f"reservation-{index}.json",
                        {"workspace_id": workspace_id, "bytes": reserve_bytes},
                    )
            except Timeout as error:
                raise ResourceError(
                    "Studio storage capacity is busy. Try again later.", 503
                ) from error
            except OSError as error:
                raise ResourceError(
                    "Studio storage is unavailable. Try again later.", 503
                ) from error
            yield


def expensive_request(scope) -> bool:
    path, method = scope["path"], scope["method"]
    if method == "POST":
        return path in {
            "/api/projects",
            "/api/sources",
            "/api/audio",
            "/api/looks",
            "/api/caption-previews",
        } or bool(
            re.fullmatch(
                r"/api/(?:project-(?:imports|creations)/[0-9a-f]{32}|projects/[0-9a-f]{32}/packages)",
                path,
            )
        )
    return method == "PUT" and bool(re.fullmatch(r"/api/projects/[0-9a-f]{32}", path))


def storage_reservation(scope) -> tuple[int, bool]:
    if scope["method"] != "POST":
        return 0, False
    path = scope["path"]
    if re.fullmatch(r"/api/project-imports/[0-9a-f]{32}", path):
        return IMPORT_PEAK_BYTES, False
    if re.fullmatch(r"/api/projects/[0-9a-f]{32}/packages", path):
        return EXPORT_PEAK_BYTES, False
    if path in {"/api/sources", "/api/audio", "/api/looks"}:
        return body_limit(scope), True
    return 0, False


class WorkAdmissionMiddleware:
    def __init__(self, app, *, limiter: WorkLimiter, workspace_id: str):
        self.app, self.limiter, self.workspace_id = app, limiter, workspace_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not expensive_request(scope):
            return await self.app(scope, receive, send)
        reserve, spool = storage_reservation(scope)
        lease = self.limiter.acquire(
            self.workspace_id, reserve_bytes=reserve, check_spool=spool
        )
        try:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(lease.__enter__)
        except ResourceError as error:
            return await JSONResponse(
                {"detail": str(error)},
                status_code=error.status,
                headers={"Retry-After": "5", "Cache-Control": "no-store"},
            )(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(lease.__exit__, None, None, None)
