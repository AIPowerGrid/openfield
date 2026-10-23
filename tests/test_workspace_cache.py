import asyncio
import hashlib
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock
from starlette.responses import JSONResponse
from test_auth import ORIGIN, google, post
from test_sequence import media  # noqa: F401 -- shared encoded-media fixture

from aipg_cinema import app, hosted
from aipg_cinema.hosted import WorkspaceCacheLimits, WorkspacePin, WorkspaceRouter


def identity(number):
    return SimpleNamespace(workspace_id=f"{number:032x}")


class FakeWorkspace:
    def __init__(self, root):
        self.root = root
        self.idle = True
        self.state = SimpleNamespace(can_evict=lambda: self.idle)

    async def __call__(self, scope, receive, send):
        await JSONResponse({"workspace": self.root.name})(scope, receive, send)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    now, created = [0.0], []

    def factory(root, *args, **kwargs):
        app = FakeWorkspace(root)
        created.append(app)
        return app

    monkeypatch.setattr(hosted, "create_app", factory)
    accounts = SimpleNamespace(resolve=lambda *args, **kwargs: identity(1))
    router = WorkspaceRouter(
        accounts,
        tmp_path / "workspaces",
        "studio.example",
        cache=WorkspaceCacheLimits(capacity=2, idle_seconds=10),
        clock=lambda: now[0],
    )
    return router, now, created


def visit(router, number):
    entry = router.acquire(identity(number))
    assert entry is not None
    router.release(entry)
    return entry


@pytest.mark.parametrize(
    "fields",
    [
        {"capacity": 0},
        {"capacity": 513},
        {"capacity": True},
        {"idle_seconds": 0},
        {"idle_seconds": float("inf")},
        {"idle_seconds": float("nan")},
        {"idle_seconds": 10**400},
        {"idle_seconds": True},
        {"idle_seconds": "900"},
    ],
)
def test_workspace_cache_config_is_bounded(fields):
    with pytest.raises(ValueError):
        WorkspaceCacheLimits(**fields)


def test_lru_recycles_quiescent_apps_without_deleting_files_or_identity(cache):
    router, now, created = cache
    first = visit(router, 1)
    marker = first.app.root / "keep.bin"
    marker.write_bytes(b"private preserved fixture")
    now[0] = 1
    second = visit(router, 2)
    now[0] = 2
    visit(router, 1)
    now[0] = 3
    visit(router, 3)
    assert set(router.apps) == {identity(1).workspace_id, identity(3).workspace_id}
    now[0] = 4
    reopened = visit(router, 2)
    assert reopened.app is not second.app
    assert (
        first.app.root.is_dir() and marker.read_bytes() == b"private preserved fixture"
    )
    assert len(router.apps) == 2 and len(created) == 4


def test_lazy_expiry_uses_completed_request_time_and_releases_idle_apps(cache):
    router, now, _ = cache
    held = router.acquire(identity(1))
    now[0] = 20
    router.release(held)
    now[0] = 21
    visit(router, 2)
    assert identity(1).workspace_id in router.apps
    now[0] = 32
    visit(router, 3)
    assert set(router.apps) == {identity(3).workspace_id}
    assert held.app.root.is_dir()


def test_inflight_and_export_workspaces_are_pinned_until_both_are_idle(cache):
    router, now, _ = cache
    held = router.acquire(identity(1))
    second = visit(router, 2)
    now[0] = 20
    with router.limiter.acquire(identity(2).workspace_id, export=True):
        assert router.acquire(identity(3)) is None
        assert set(router.apps) == {identity(1).workspace_id, identity(2).workspace_id}
        router.release(held)
        visit(router, 3)
        assert identity(2).workspace_id in router.apps
        assert second.app.root.is_dir()
    now[0] = 40
    visit(router, 4)
    assert identity(2).workspace_id not in router.apps


def test_child_startup_before_work_lock_is_also_pinned(cache):
    router, now, _ = cache
    first = visit(router, 1)
    second = visit(router, 2)
    first.app.idle = second.app.idle = False
    now[0] = 20
    assert router.acquire(identity(3)) is None
    first.app.idle = True
    visit(router, 3)
    assert router.apps[second.workspace_id] is second


@pytest.mark.parametrize("result", [None, "unknown", "error"])
def test_unknown_activity_is_not_assumed_idle(cache, result):
    router, _, _ = cache
    first = visit(router, 1)
    second = visit(router, 2)

    def status():
        if result == "error":
            raise OSError("private failure")
        return result

    first.app.state.can_evict = status
    second.app.state.can_evict = status
    assert router.acquire(identity(3)) is None
    assert len(router.apps) == 2


def test_rejected_capacity_does_not_create_a_workspace_and_current_reads_still_work(
    cache,
):
    router, _, _ = cache
    a, b = router.acquire(identity(1)), router.acquire(identity(2))
    assert router.acquire(identity(3)) is None
    assert not (router.directory / identity(3).workspace_id).exists()
    extra = router.acquire(identity(1))
    assert extra is a and a.requests == 2
    router.release(extra)
    router.release(a)
    router.release(b)
    assert a.requests == b.requests == 0


def test_concurrent_requests_share_one_constructed_app_and_balance_pins(cache):
    router, _, created = cache
    with ThreadPoolExecutor(max_workers=8) as pool:
        entries = list(pool.map(lambda _: router.acquire(identity(1)), range(16)))
    assert len(created) == 1 and entries[0].requests == 16
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(router.release, entries))
    assert entries[0].requests == 0


def test_abandoned_admission_cannot_pin_or_create_a_workspace(cache):
    router, _, _ = cache
    pin = WorkspacePin()
    router.finish(pin)
    assert router.acquire(identity(1), pin) is None
    assert not router.apps
    pin = WorkspacePin()
    entry = router.acquire(identity(1), pin)
    assert pin.entry is entry and entry.requests == 1
    router.finish(pin)
    router.finish(pin)
    assert pin.entry is None and entry.requests == 0
    with pytest.raises(RuntimeError, match="Unbalanced"):
        router.release(entry)


def scope():
    return {
        "type": "http",
        "method": "GET",
        "path": "/api/config",
        "root_path": "",
        "headers": [],
        "query_string": b"",
        "scheme": "https",
        "server": ("studio.example", 443),
    }


def test_cancelled_response_releases_request_pin(cache):
    router, _, _ = cache
    entry = visit(router, 1)

    async def run():
        entered = asyncio.Event()

        async def waiting(scope, receive, send):
            entered.set()
            await asyncio.Event().wait()

        entry.app = waiting

        async def unused(*args):
            raise AssertionError

        task = asyncio.create_task(router(scope(), unused, unused))
        await asyncio.wait_for(entered.wait(), 5)
        assert entry.requests == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert entry.requests == 0

    asyncio.run(run())


def test_cancellation_during_threadpool_admission_does_not_leak_a_pin(
    cache, monkeypatch
):
    router, _, _ = cache
    entered, release = threading.Event(), threading.Event()
    acquire = router.acquire

    def delayed(*args):
        entry = acquire(*args)
        entered.set()
        assert release.wait(5)
        return entry

    monkeypatch.setattr(router, "acquire", delayed)

    async def run():
        async def unused(*args):
            raise AssertionError

        task = asyncio.create_task(router(scope(), unused, unused))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        assert router.apps[identity(1).workspace_id].requests == 0

    asyncio.run(run())


def test_slow_response_remains_pinned_until_final_body_has_been_sent(cache):
    router, _, _ = cache
    first = visit(router, 1)
    visit(router, 2)

    async def run():
        blocked, release = asyncio.Event(), asyncio.Event()

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.body":
                blocked.set()
                await release.wait()

        task = asyncio.create_task(router(scope(), receive, send))
        await asyncio.wait_for(blocked.wait(), 5)
        assert first.requests == 1
        visit(router, 3)
        assert router.apps[first.workspace_id] is first
        release.set()
        await task
        assert first.requests == 0

    asyncio.run(run())


def test_stale_lock_files_do_not_count_as_live_work(cache):
    router, _, _ = cache
    visit(router, 1)
    workspace = identity(1).workspace_id
    assert not router.limiter.busy(workspace)
    with FileLock(router.limiter.root / f"export-{workspace}-0.lock"):
        assert router.limiter.busy(workspace)
    assert not router.limiter.busy(workspace)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_real_export_pins_cache_then_reopens_unchanged_after_eviction(
    login_api,
    tmp_path,
    media,  # noqa: F811 -- imported pytest fixture
    monkeypatch,
):
    _, calls, _, _, open_client = login_api
    first = open_client(hosted=True, cache=WorkspaceCacheLimits(capacity=1))
    second = TestClient(first.app, base_url=ORIGIN)
    state_a = google(first).json()
    state_b = google(second, "proof-b").json()
    original_handle = first.cookies.get("__Host-studio-session")
    project = post(
        first,
        "/api/projects",
        {"title": "Pinned offline export", "frame_format": "square"},
        state_a["csrf"],
    ).json()
    router = first.app.routes[-1].app
    old_entry = router.apps[state_a["workspace_id"]]
    workspace = tmp_path / "workspaces" / state_a["workspace_id"]
    hashes = {}
    for number, shot in enumerate(project["shots"], 1):
        take_id = f"{number:032x}"
        shutil.copytree(media / take_id, workspace / "jobs" / take_id)
        shot["selected_take_id"] = take_id
        hashes[take_id] = hashlib.sha256(
            (workspace / "jobs" / take_id / "render/reshoot.mp4").read_bytes()
        ).hexdigest()
    saved = first.put(
        f"/api/projects/{project['id']}",
        json=project,
        headers={"origin": ORIGIN, "x-studio-csrf": state_a["csrf"]},
    )
    assert saved.status_code == 200, saved.text
    project = saved.json()
    gate, wrapper = tmp_path / "continue-export", tmp_path / "export-startup.py"
    wrapper.write_text("""import os,sys,time
from pathlib import Path
gate=Path(sys.argv[1])
deadline=time.monotonic()+30
while not gate.exists():
    if time.monotonic()>deadline:
        raise RuntimeError("Test startup gate timed out")
    time.sleep(.01)
os.execv(sys.executable,[sys.executable,*sys.argv[2:]])
""")
    popen = app.subprocess.Popen
    processes = []

    def tracked(arguments, *args, **kwargs):
        if len(arguments) > 2 and arguments[2] == "aipg_cinema.sequence":
            process = popen(
                [arguments[0], str(wrapper), str(gate), *arguments[1:]], *args, **kwargs
            )
            processes.append(process)
            return process
        return popen(arguments, *args, **kwargs)

    monkeypatch.setattr(app.subprocess, "Popen", tracked)
    body = {"request_id": "f" * 32, "revision": project["revision"]}
    url = f"/api/projects/{project['id']}/exports"
    try:
        result = post(first, url, body, state_a["csrf"])
        assert result.status_code == 200, result.text
        assert result.json()["active"] and result.json()["status"] == "queued"
        assert len(processes) == 1 and processes[0].poll() is None
        # No observer/work slot exists yet: the live child startup handle pins it.
        assert not router.limiter.busy(state_a["workspace_id"])
        denied = second.get("/api/config")
        assert denied.status_code == 503 and denied.headers["retry-after"] == "5"
        assert router.apps[state_a["workspace_id"]] is old_entry
        assert first.get("/api/config").status_code == 200
        gate.touch()
        assert processes[0].wait(timeout=60) == 0
        receipt = first.get("/api/exports/" + body["request_id"]).json()
        assert receipt["status"] == "succeeded" and receipt["active"] is False
        output = first.get(receipt["output_url"]).content
        assert output and len(output) > 1000
        assert second.get("/api/config").status_code == 200
        assert set(router.apps) == {state_b["workspace_id"]}
        assert second.get(f"/api/projects/{project['id']}").status_code == 404
        assert second.get(receipt["output_url"]).status_code == 404
        calls.clear()
        assert first.get(f"/api/projects/{project['id']}").json() == project
        assert router.apps[state_a["workspace_id"]] is not old_entry
        assert first.cookies.get("__Host-studio-session") == original_handle
        assert first.get(receipt["output_url"]).content == output
        assert (
            post(first, url, body, state_a["csrf"]).json()["id"] == body["request_id"]
        )
        assert len(processes) == 1
        assert first.get(url).json() == [receipt]
        assert all(
            hashlib.sha256(
                (workspace / "jobs" / take_id / "render/reshoot.mp4").read_bytes()
            ).hexdigest()
            == digest
            for take_id, digest in hashes.items()
        )
        assert not any(
            call.url.path.endswith("/auth/google/exchange") for call in calls
        )
    finally:
        gate.touch()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except app.subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
