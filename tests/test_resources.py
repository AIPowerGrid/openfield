import asyncio
import json
import os
import select
import subprocess
import sys
from dataclasses import replace

import httpx
import pytest
import starlette.formparsers
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from aipg_cinema import app, resources, sequence
from aipg_cinema.project import NewProject, ProjectStore
from aipg_cinema.resources import (
    MIB,
    RequestLimitsMiddleware,
    ResourceError,
    WorkAdmissionMiddleware,
    WorkLimiter,
    WorkLimits,
    below_storage_limit,
    body_limit,
    storage_reservation,
)
from aipg_cinema.transfer_limits import (
    EXPORT_PEAK_BYTES,
    IMPORT_PEAK_BYTES,
    MAX_ARCHIVE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_MEDIA_BYTES,
    MAX_REBUILT_METADATA_BYTES,
)


@pytest.fixture
def limiter(tmp_path):
    workspaces = tmp_path / "workspaces"
    for name in ("a" * 32, "b" * 32):
        (workspaces / name).mkdir(parents=True)
    return WorkLimiter(
        tmp_path / "resources",
        workspaces,
        WorkLimits(concurrent=2, per_workspace=1, minimum_free_bytes=0),
    )


@pytest.mark.parametrize(
    "path,size",
    [
        ("/api/sources", 101 * MIB),
        ("/api/audio", 51 * MIB),
        ("/api/looks", 13 * MIB),
        ("/api/project-imports/" + "a" * 32, 514 * MIB),
        ("/api/projects", 2 * MIB),
        ("/auth/google", 48 * 1024),
        ("/api/project-imports/not-a-real-id", 2 * MIB),
    ],
)
def test_body_limits_cover_actual_routes_and_unknown_routes(path, size):
    assert body_limit({"method": "POST", "path": path}) == size


class Chunks(httpx.AsyncByteStream):
    def __init__(self, values):
        self.values = values
        self.read = 0

    async def __aiter__(self):
        for value in self.values:
            self.read += 1
            if isinstance(value, float):
                await asyncio.sleep(value)
            elif callable(value):
                value()
            else:
                yield value


def multipart(values):
    return Chunks(
        [
            b'--test\r\nContent-Disposition: form-data; name="file"; filename="frame.png"\r\nContent-Type: image/png\r\n\r\n',
            *values,
            b"\r\n--test--\r\n",
        ]
    )


@pytest.mark.parametrize("claimed_length", [None, "1"])
def test_chunked_multipart_stops_before_endpoint_and_closes_spooled_files(
    tmp_path, monkeypatch, claimed_length
):
    handles = []
    errors = []
    original = starlette.formparsers.SpooledTemporaryFile
    parse = starlette.formparsers.MultiPartParser.parse

    async def observed(parser):
        try:
            return await parse(parser)
        except BaseException as error:
            errors.append(repr(error))
            raise

    def tracked(*args, **kwargs):
        handle = original(*args, **kwargs)
        handles.append(handle)
        return handle

    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected bodies must not reach the media decoder.")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)
    monkeypatch.setattr(starlette.formparsers.MultiPartParser, "parse", observed)
    monkeypatch.setattr(resources, "body_limit", lambda scope: 2 * MIB)
    monkeypatch.setattr(app, "prepare_look", forbidden)
    service = app.create_app(tmp_path, "self-hosted", inference_enabled=False)
    stream = multipart([b"x" * MIB, b"y" * MIB, b"z" * MIB])

    async def run():
        headers = {"content-type": "multipart/form-data; boundary=test"}
        if claimed_length:
            headers["content-length"] = claimed_length
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service), base_url="http://localhost"
        ) as client:
            response = await client.post("/api/looks", content=stream, headers=headers)
            assert response.status_code == 413, (response.text, errors)
            assert response.headers["cache-control"] == "no-store"

    asyncio.run(run())
    assert stream.read == 3  # Header plus two chunks; no remainder is drained.
    assert handles and all(handle.closed for handle in handles)
    assert not list((tmp_path / "looks").iterdir())


@pytest.mark.parametrize("deadline", ["idle", "total"])
def test_slow_upload_deadlines_close_spooled_files(tmp_path, monkeypatch, deadline):
    handles = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        handle = original(*args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)
    now = [0]
    values = [
        b"x" * (MIB + 1),
        0.1 if deadline == "idle" else lambda: now.__setitem__(0, 11),
        b"y",
    ]
    service = RequestLimitsMiddleware(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        idle_seconds=0.02 if deadline == "idle" else 1,
        body_seconds=30 if deadline == "idle" else 10,
        clock=None if deadline == "idle" else lambda: now[0],
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service), base_url="http://localhost"
        ) as client:
            response = await client.post(
                "/api/looks",
                content=multipart(values),
                headers={
                    "content-type": "multipart/form-data; boundary=test",
                },
            )
            assert response.status_code == 408, response.text

    asyncio.run(run())
    assert handles and all(handle.closed for handle in handles)
    assert not list((tmp_path / "looks").iterdir())


@pytest.mark.parametrize("lengths", [["-1"], ["oops"], [""], ["1", "2"]])
def test_bad_content_length_is_rejected_without_consuming_the_body(lengths):
    service = RequestLimitsMiddleware(JSONResponse({"unexpected": True}))

    async def run():
        messages = []

        async def receive():
            raise AssertionError("Invalid declared lengths must fail before receive.")

        async def send(message):
            messages.append(message)

        await service(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/looks",
                "headers": [(b"content-length", value.encode()) for value in lengths],
            },
            receive,
            send,
        )
        assert messages[0]["status"] == 400

    asyncio.run(run())


def test_body_deadline_does_not_cancel_processing_after_the_upload():
    service = FastAPI()
    now = [0]

    @service.post("/api/projects")
    async def work(request: Request):
        await request.body()
        now[0] = 100
        return {"complete": True}

    service.add_middleware(
        RequestLimitsMiddleware, idle_seconds=1, body_seconds=10, clock=lambda: now[0]
    )
    assert TestClient(service).post("/api/projects", json={}).json() == {
        "complete": True
    }


@pytest.mark.parametrize("path", ["/api/sources", "/api/looks", "/api/audio"])
def test_extra_multipart_files_fail_before_any_decoder(tmp_path, monkeypatch, path):
    handles = []
    original = starlette.formparsers.SpooledTemporaryFile

    def tracked(*args, **kwargs):
        handle = original(*args, **kwargs)
        handles.append(handle)
        return handle

    def forbidden(*args, **kwargs):
        raise AssertionError("Extra uploads must not reach decoders.")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)
    for name in ("probe", "prepare_source", "prepare_look", "audio_info"):
        monkeypatch.setattr(app, name, forbidden)
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    response = client.post(
        path,
        files=[
            ("file", ("first.png", b"first")),
            ("other", ("ignored.png", b"second")),
        ],
    )
    assert response.status_code == 400
    assert handles and all(handle.closed for handle in handles)
    assert all(
        not list((tmp_path / name).iterdir()) for name in ("sources", "looks", "audio")
    )


def test_account_and_global_slots_release_after_rejection_and_exceptions(limiter):
    other = WorkLimiter.reopen(limiter.root)
    with limiter.acquire("a" * 32):
        with pytest.raises(ResourceError), other.acquire("a" * 32):
            pytest.fail("The same account cannot exceed its slot count.")
        with other.acquire("b" * 32):
            pass
    with pytest.raises(RuntimeError), limiter.acquire("a" * 32):
        raise RuntimeError("Failure after admission")
    with other.acquire("a" * 32), other.acquire("b" * 32):
        pass


def test_global_slots_apply_across_accounts_and_configurations_cannot_diverge(limiter):
    with pytest.raises(ValueError, match="policy differs"):
        WorkLimiter(
            limiter.root, limiter.workspaces, replace(limiter.limits, concurrent=1)
        )
    second = WorkLimiter(
        limiter.root.parent / "one-slot",
        limiter.workspaces,
        replace(limiter.limits, concurrent=1),
    )
    with (
        second.acquire("a" * 32),
        pytest.raises(ResourceError),
        second.acquire("b" * 32),
    ):
        pytest.fail("Global capacity must apply across accounts.")
    with second.acquire("b" * 32):
        pass


def test_only_one_export_per_workspace_runs_while_an_upload_can_use_other_capacity(
    limiter,
):
    shared = WorkLimiter(
        limiter.root.parent / "shared",
        limiter.workspaces,
        replace(limiter.limits, concurrent=4, per_workspace=2),
    )
    with shared.acquire("a" * 32, export=True):
        with (
            pytest.raises(ResourceError),
            WorkLimiter.reopen(shared.root).acquire("a" * 32, export=True),
        ):
            pytest.fail(
                "Another web process must not run a second export for the same workspace."
            )
        with shared.acquire("a" * 32), shared.acquire("b" * 32, export=True):
            pass
    with shared.acquire("a" * 32, export=True):
        pass


def test_slots_are_held_by_the_process_and_release_after_termination(limiter):
    if os.name != "posix":
        pytest.skip("Hosted staging currently requires POSIX owner-only storage.")
    code = """import sys
from pathlib import Path
from aipg_cinema.resources import WorkLimiter
with WorkLimiter.reopen(Path(sys.argv[1])).acquire('a'*32):
 print('ready', flush=True)
 sys.stdin.read()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(limiter.root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PATH": os.environ.get("PATH", os.defpath)},
    )
    try:
        assert select.select([process.stdout], [], [], 5)[0], (
            "Child did not acquire its slot."
        )
        assert process.stdout.readline() == b"ready\n"
        with (
            pytest.raises(ResourceError),
            WorkLimiter.reopen(limiter.root).acquire("a" * 32),
        ):
            pytest.fail("A live child must retain its admission after app restart.")
        process.terminate()
        process.communicate(timeout=5)
        with limiter.acquire("a" * 32):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("reason", ["workspace", "total", "free", "symlink", "entries"])
def test_storage_admission_fails_closed_and_never_deletes_existing_data(
    limiter, monkeypatch, reason
):
    reference = limiter.workspaces / ("a" * 32) / "keep.bin"
    reference.write_bytes(b"keep")
    settings = {}
    if reason == "workspace":
        settings["workspace_bytes"] = 4
    elif reason == "total":
        settings.update(workspace_bytes=4, total_bytes=4)
        reference.unlink()
        (limiter.workspaces / ("b" * 32) / "keep.bin").write_bytes(b"keep")
    elif reason == "free":
        monkeypatch.setattr(
            resources.shutil, "disk_usage", lambda path: type("Disk", (), {"free": 0})()
        )
        settings["minimum_free_bytes"] = 1
    elif reason == "symlink":
        (reference.parent / "link").symlink_to(reference)
    else:
        settings["scan_entries"] = 1
    limited = WorkLimiter(
        limiter.root.parent / ("limits-" + reason),
        limiter.workspaces,
        replace(limiter.limits, **settings),
    )
    with pytest.raises(ResourceError) as caught, limited.acquire("a" * 32):
        pytest.fail("Storage admission must reject this workspace.")
    assert caught.value.status == 507
    assert any(p.read_bytes() == b"keep" for p in limiter.workspaces.glob("*/keep.bin"))


def test_storage_count_never_follows_a_symlink_outside_the_workspace(tmp_path):
    store = tmp_path / "workspace"
    store.mkdir()
    (store / "escape").symlink_to(tmp_path / "missing")
    assert not below_storage_limit(store, 10000, 100)


@pytest.mark.parametrize("boundary", ["workspace", "total", "free", "spool"])
def test_concurrent_uploads_reserve_capacity_before_they_write(
    tmp_path, monkeypatch, boundary
):
    workspaces = tmp_path / "workspaces"
    for name in ("a" * 32, "b" * 32):
        (workspaces / name).mkdir(parents=True)
    limits = WorkLimits(
        concurrent=2,
        per_workspace=2,
        minimum_free_bytes=0,
        workspace_bytes=100 if boundary in ("workspace", "total") else 1000,
        total_bytes=1000 if boundary != "total" else 100,
    )
    limited = WorkLimiter(tmp_path / "resources", workspaces, limits)
    other = WorkLimiter.reopen(limited.root)
    if boundary in ("free", "spool"):
        monkeypatch.setattr(
            resources.shutil,
            "disk_usage",
            lambda path: type(
                "Disk",
                (),
                {"free": 100 if boundary == "free" or path != workspaces else 1000},
            )(),
        )
    # Nothing is written yet. The second upload must still see the first claim.
    with limited.acquire("a" * 32, reserve_bytes=60):
        second_workspace = "a" * 32 if boundary == "workspace" else "b" * 32
        with (
            pytest.raises(ResourceError) as caught,
            other.acquire(second_workspace, reserve_bytes=60),
        ):
            pytest.fail("Concurrent uploads cannot promise the same storage.")
        assert caught.value.status == 507
    with other.acquire(second_workspace, reserve_bytes=60):
        pass
    assert not list(workspaces.glob("*/*"))


def test_reservations_release_on_failure_and_ignore_unheld_stale_records(limiter):
    with pytest.raises(RuntimeError), limiter.acquire("a" * 32, reserve_bytes=123):
        raise RuntimeError("Upload disconnected")
    with WorkLimiter.reopen(limiter.root).acquire("a" * 32, reserve_bytes=123):
        pass


def test_simultaneous_processes_cannot_reserve_the_same_capacity(tmp_path):
    if os.name != "posix":
        pytest.skip("Hosted staging currently requires POSIX owner-only storage.")
    workspaces = tmp_path / "workspaces"
    for name in ("a" * 32, "b" * 32):
        (workspaces / name).mkdir(parents=True)
    limited = WorkLimiter(
        tmp_path / "resources",
        workspaces,
        WorkLimits(
            concurrent=2,
            per_workspace=1,
            minimum_free_bytes=0,
            workspace_bytes=100,
            total_bytes=100,
        ),
    )
    code = """import json,sys
from pathlib import Path
from aipg_cinema.resources import WorkLimiter,ResourceError
sys.stdin.readline()
try:
 with WorkLimiter.reopen(Path(sys.argv[1])).acquire(sys.argv[2],reserve_bytes=60):
  print(json.dumps({'admitted':True}),flush=True)
  sys.stdin.readline()
except ResourceError as error:
 print(json.dumps({'rejected':error.status}),flush=True)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(limited.root), name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
        for name in ("a" * 32, "b" * 32)
    ]
    try:
        for process in children:
            process.stdin.write(b"start\n")
            process.stdin.flush()
        states = []
        for process in children:
            assert select.select([process.stdout], [], [], 5)[0], (
                "Child did not resolve its upload admission."
            )
            states.append(json.loads(process.stdout.readline()))
        assert states.count({"admitted": True}) == 1
        assert states.count({"rejected": 507}) == 1
        winner = children[states.index({"admitted": True})]
        # A crash leaves a bounded record, but its OS-held lease must disappear.
        winner.terminate()
        winner.communicate(timeout=5)
        with WorkLimiter.reopen(limited.root).acquire("a" * 32, reserve_bytes=60):
            pass
        assert not list(workspaces.glob("*/*"))
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("damage", ["missing", "json", "oversized", "negative"])
def test_live_reservation_damage_rejects_safely_then_stale_record_is_ignored(
    limiter, damage
):
    with limiter.acquire("a" * 32, reserve_bytes=60):
        record = next(limiter.root.glob("reservation-*.json"))
        if damage == "missing":
            record.unlink()
        elif damage == "json":
            record.write_text("not JSON")
        elif damage == "oversized":
            record.write_text("x" * 4097)
        else:
            record.write_text(json.dumps({"workspace_id": "a" * 32, "bytes": -1}))
        with (
            pytest.raises(ResourceError) as caught,
            WorkLimiter.reopen(limiter.root).acquire("b" * 32, reserve_bytes=60),
        ):
            pytest.fail("Unknown live storage reservations must fail closed.")
        assert caught.value.status == 503
        assert str(limiter.root) not in str(caught.value)
    with WorkLimiter.reopen(limiter.root).acquire("b" * 32, reserve_bytes=60):
        pass


@pytest.mark.parametrize("value", [-1, True, 1.5, "60"])
def test_upload_reservation_sizes_are_server_owned_whole_bytes(limiter, value):
    with pytest.raises(ValueError), limiter.acquire("a" * 32, reserve_bytes=value):
        pytest.fail("Reject an invalid reservation before acquiring work.")
    with limiter.acquire("a" * 32):
        pass


@pytest.mark.parametrize("declared", [None, "1"])
def test_upload_reservation_uses_body_ceiling_not_untrusted_declared_size(
    limiter, declared
):
    limits = replace(limiter.limits, workspace_bytes=10 * MIB)
    limited = WorkLimiter(
        limiter.root.parent / "small-budget", limiter.workspaces, limits
    )
    reads = []

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b"unread", "more_body": False}

    async def downstream(scope, receive, send):
        await receive()
        pytest.fail("An unadmitted upload must not reach parsing or decoding.")

    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(
        WorkAdmissionMiddleware(downstream, limiter=limited, workspace_id="a" * 32)(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/looks",
                "headers": []
                if declared is None
                else [(b"content-length", declared.encode())],
            },
            receive,
            send,
        )
    )
    assert reads == []
    assert sent[0]["status"] == 507


@pytest.mark.parametrize("kind", ["import", "package"])
@pytest.mark.parametrize("declared", [None, "1"])
def test_transfer_growth_is_reserved_before_reading_body(limiter, kind, declared):
    limited = WorkLimiter(
        limiter.root.parent / ("growth-" + kind),
        limiter.workspaces,
        replace(limiter.limits, workspace_bytes=600 * MIB),
    )
    reads, sent = [], []

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b"unread", "more_body": False}

    async def downstream(scope, receive, send):
        await receive()
        pytest.fail("Reserve expansion/copy/archive capacity before parsing.")

    async def send(message):
        sent.append(message)

    path = (
        "/api/project-imports/" + "c" * 32
        if kind == "import"
        else "/api/projects/" + "c" * 32 + "/packages"
    )
    asyncio.run(
        WorkAdmissionMiddleware(downstream, limiter=limited, workspace_id="a" * 32)(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": []
                if declared is None
                else [(b"content-length", declared.encode())],
            },
            receive,
            send,
        )
    )
    assert reads == []
    assert sent[0]["status"] == 507


def test_workspace_transfers_do_not_require_unused_multipart_spool_space(
    limiter, monkeypatch
):
    monkeypatch.setattr(
        resources.shutil,
        "disk_usage",
        lambda path: type(
            "Disk", (), {"free": 1024 if path == limiter.workspaces else 0}
        )(),
    )
    with limiter.acquire("a" * 32, reserve_bytes=100, check_spool=False):
        pass
    with pytest.raises(ResourceError), limiter.acquire("a" * 32, reserve_bytes=100):
        pytest.fail("Multipart uploads still need temporary-spool headroom.")


def test_transfer_reservation_matches_format_caps_and_concurrent_growth(limiter):
    assert (
        IMPORT_PEAK_BYTES
        == MAX_ARCHIVE_BYTES
        + 2 * MAX_MEDIA_BYTES
        + MAX_REBUILT_METADATA_BYTES
        + MAX_MANIFEST_BYTES
    )
    assert EXPORT_PEAK_BYTES == MAX_MEDIA_BYTES + MAX_ARCHIVE_BYTES + MAX_MANIFEST_BYTES
    assert storage_reservation(
        {"method": "POST", "path": "/api/project-imports/" + "c" * 32}
    ) == (IMPORT_PEAK_BYTES, False)
    assert storage_reservation(
        {"method": "POST", "path": "/api/projects/" + "c" * 32 + "/packages"}
    ) == (EXPORT_PEAK_BYTES, False)
    assert storage_reservation({"method": "POST", "path": "/api/looks"}) == (
        13 * MIB,
        True,
    )
    assert storage_reservation(
        {"method": "GET", "path": "/api/project-imports/" + "c" * 32}
    ) == (0, False)
    limited = WorkLimiter(
        limiter.root.parent / "transfer-concurrency",
        limiter.workspaces,
        replace(limiter.limits, workspace_bytes=2 * 1024**3, total_bytes=2 * 1024**3),
    )
    with limited.acquire("a" * 32, reserve_bytes=IMPORT_PEAK_BYTES, check_spool=False):
        with (
            pytest.raises(ResourceError) as caught,
            WorkLimiter.reopen(limited.root).acquire(
                "b" * 32, reserve_bytes=EXPORT_PEAK_BYTES, check_spool=False
            ),
        ):
            pytest.fail("Concurrent transfers must reserve all their planned growth.")
        assert caught.value.status == 507
    with limited.acquire("b" * 32, reserve_bytes=EXPORT_PEAK_BYTES, check_spool=False):
        pass


@pytest.mark.parametrize("mismatch", [None, {"import": 1, "package": 1}])
def test_old_or_mismatched_transfer_policy_is_never_silently_replaced(
    limiter, mismatch
):
    policy = limiter.root / "policy.json"
    settings = json.loads(policy.read_text())
    if mismatch is None:
        settings.pop("transfer_peak_bytes")
    else:
        settings["transfer_peak_bytes"] = mismatch
    policy.write_text(json.dumps(settings))
    before = policy.read_bytes()
    kept = limiter.workspaces / ("a" * 32) / "keep.bin"
    kept.write_bytes(b"Never delete existing projects to upgrade resource policy.")
    with pytest.raises(ValueError, match="policy differs"):
        WorkLimiter.reopen(limiter.root)
    assert policy.read_bytes() == before
    assert (
        kept.read_bytes()
        == b"Never delete existing projects to upgrade resource policy."
    )


def test_cached_package_receipts_and_downloads_survive_full_storage(limiter):
    workspace = limiter.workspaces / ("a" * 32)
    project = ProjectStore(workspace / "projects").create(NewProject())
    folder = workspace / "packages" / ("b" * 32)
    folder.mkdir(parents=True)
    intent = {
        "project_id": project.id,
        "revision": project.revision,
        "project": project.model_dump(),
    }
    (folder / "request.json").write_text(json.dumps(intent))
    (folder / "project.aipg.zip").write_bytes(
        b"Existing cached bytes; not a ZIP parser fixture."
    )
    limited = WorkLimiter(
        limiter.root.parent / "full-store",
        limiter.workspaces,
        replace(limiter.limits, workspace_bytes=1),
    )
    client = TestClient(
        app.create_app(
            workspace, "self-hosted", inference_enabled=False, work_limiter=limited
        ),
        base_url="http://localhost",
    )
    assert (
        client.get("/api/project-packages/" + "b" * 32).json()["status"] == "complete"
    )
    assert (
        client.get("/api/project-packages/" + "b" * 32 + "/download").content
        == (folder / "project.aipg.zip").read_bytes()
    )
    response = client.post(
        f"/api/projects/{project.id}/packages",
        json={"request_id": "c" * 32, "revision": project.revision},
    )
    assert response.status_code == 507
    assert not (folder.parent / ("c" * 32)).exists()
    assert json.loads((folder / "request.json").read_text()) == intent


def test_busy_admission_rejects_before_upload_and_does_not_block_status_or_receipts(
    limiter,
):
    service = FastAPI()

    @service.post("/api/looks")
    async def upload(request: Request):
        await request.body()
        return {"complete": True}

    @service.get("/api/jobs")
    async def status():
        return {"status": "running"}

    service.add_middleware(
        WorkAdmissionMiddleware, limiter=limiter, workspace_id="a" * 32
    )
    client = TestClient(service)
    with limiter.acquire("a" * 32):
        response = client.post("/api/looks", content=b"unread")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert client.get("/api/jobs").json() == {"status": "running"}
    assert client.post("/api/looks", content=b"new").status_code == 200


def test_project_creation_receipt_remains_readable_while_capacity_is_busy(limiter):
    workspace = limiter.workspaces / ("a" * 32)
    client = TestClient(
        app.create_app(
            workspace, "self-hosted", inference_enabled=False, work_limiter=limiter
        ),
        base_url="http://localhost",
    )
    path = "/api/project-creations/" + "b" * 32
    created = client.post(path, json={"title": "One saved short"})
    assert created.status_code == 200
    with limiter.acquire("a" * 32):
        assert client.get(path).json() == created.json()
        assert (
            client.post(
                "/api/project-creations/" + "c" * 32,
                json={"title": "Not admitted"},
            ).status_code
            == 429
        )
    assert len(client.get("/api/projects").json()) == 1


def test_request_cancellation_releases_its_capacity(limiter):
    async def run():
        entered = asyncio.Event()

        async def waiting(scope, receive, send):
            entered.set()
            await asyncio.Event().wait()

        async def unused():
            raise AssertionError

        service = WorkAdmissionMiddleware(
            waiting, limiter=limiter, workspace_id="a" * 32
        )
        task = asyncio.create_task(
            service(
                {"type": "http", "method": "POST", "path": "/api/looks"}, unused, unused
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with limiter.acquire("a" * 32):
            pass

    asyncio.run(run())


def test_cached_source_playback_survives_busy_work_but_new_previews_need_admission(
    limiter, monkeypatch
):
    workspace = limiter.workspaces / ("a" * 32)
    client = TestClient(
        app.create_app(
            workspace, "self-hosted", inference_enabled=False, work_limiter=limiter
        ),
        base_url="http://localhost",
    )
    source = workspace / "sources" / ("c" * 32)
    (source / "preview").mkdir(parents=True)
    (source / "source.mp4").write_bytes(b"original fixture")
    (source / "preview/source.mp4").write_bytes(b"cached fixture")

    def forbidden(*args, **kwargs):
        raise AssertionError("Busy capacity must not admit a decoder.")

    monkeypatch.setattr(app, "prepare_source", forbidden)
    with limiter.acquire("a" * 32):
        assert client.get("/api/sources/" + "c" * 32).content == b"cached fixture"
        assert (
            client.get("/api/sources/" + "c" * 32 + "?source_start=1").status_code
            == 429
        )
        assert client.get("/api/config").status_code == 200
        assert client.get("/api/projects").status_code == 200


def test_hosted_upload_rejection_closes_parser_files_and_releases_work_slot(
    limiter, monkeypatch
):
    workspace = limiter.workspaces / ("a" * 32)
    service = app.create_app(
        workspace, "self-hosted", inference_enabled=False, work_limiter=limiter
    )
    monkeypatch.setattr(resources, "body_limit", lambda scope: 1024)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service), base_url="http://localhost"
        ) as client:
            response = await client.post(
                "/api/looks",
                content=multipart([b"x" * 2048]),
                headers={"content-type": "multipart/form-data; boundary=test"},
            )
            assert response.status_code == 413

    asyncio.run(run())
    assert not list((workspace / "looks").iterdir())
    with limiter.acquire("a" * 32):
        pass


def test_export_cli_holds_the_shared_budget_for_assembly_and_retains_failed_settings(
    limiter, monkeypatch
):
    workspace = limiter.workspaces / ("a" * 32)
    jobs, exports = workspace / "jobs", workspace / "exports"
    jobs.mkdir()
    projects = ProjectStore(workspace / "projects")
    project = projects.create(NewProject(title="Budgeted export"))
    output = exports / ("c" * 32)
    output.mkdir(parents=True)
    (output / "project.json").write_text(project.model_dump_json())
    command = [
        "sequence",
        "--project",
        str(output / "project.json"),
        "--jobs",
        str(jobs),
        "--directory",
        str(output),
        "--resource-root",
        str(limiter.root),
    ]
    monkeypatch.setattr(sys, "argv", command)
    called = []

    def assemble(*args):
        with pytest.raises(ResourceError), limiter.acquire("a" * 32):
            pytest.fail("Assembly must retain its workspace slot.")
        called.append(True)

    monkeypatch.setattr(sequence, "assemble", assemble)
    assert sequence.main() == 0
    assert called == [True]
    with limiter.acquire("a" * 32):
        assert sequence.main() == 1
    assert called == [True]
    assert json.loads((output / "state.json").read_text())["status"] == "failed"
    assert (output / "project.json").read_text() == project.model_dump_json()
