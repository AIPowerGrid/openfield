import json
import select
import shutil
import sqlite3
import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from filelock import FileLock, Timeout
from test_auth import google, post

from aipg_cinema import maintenance as ops
from aipg_cinema import sequence
from aipg_cinema.core_accounts import CoreAccounts
from aipg_cinema.hosted import create_hosted_app
from aipg_cinema.hosted_server import StagingConfig, staging_app
from aipg_cinema.sessions import AccountSessions, SessionError
from aipg_cinema.store_activity import StoreBusy, file_lease, store_activity


@pytest.fixture
def store(login_api, tmp_path):
    client = login_api[-1](hosted=True)
    identity = google(client).json()
    project = post(
        client,
        "/api/projects",
        {"title": "Restore me", "frame_format": "square"},
        identity["csrf"],
    ).json()
    return tmp_path, identity, project


def clone_store(root, tmp_path_factory):
    clone = tmp_path_factory.mktemp("relocated-store").resolve()
    shutil.copytree(root / "auth", clone / "auth")
    shutil.copytree(root / "workspaces", clone / "workspaces")
    (clone / ".workspaces-resources").mkdir(mode=0o700)
    shutil.copy2(
        root / ".workspaces-resources/policy.json",
        clone / ".workspaces-resources/policy.json",
    )
    return clone


def test_shared_writers_exclude_maintenance_without_changing_lock_file(store):
    root = store[0]
    with (
        store_activity(root),
        store_activity(root),
        pytest.raises(StoreBusy),
        ops.maintenance(root),
    ):
        pytest.fail("Active writers must exclude maintenance.")
    with ops.maintenance(root), pytest.raises(StoreBusy), store_activity(root):
        pytest.fail("Maintenance must exclude late writers.")
    with store_activity(root):
        pass
    path = root / ".store-activity.lock"
    inode = path.stat().st_ino
    with pytest.raises(RuntimeError), store_activity(root):
        raise RuntimeError("fault")
    assert path.stat().st_ino == inode
    assert path.stat().st_mode & 0o777 == 0o600


def test_managed_server_cannot_initialize_while_maintenance_is_held(store):
    root, _, _ = store
    key = root / "test-key"
    key.write_text("test-only-key")
    key.chmod(0o600)
    config = StagingConfig(
        root, key, "https://studio.example", "public-client", "a" * 64
    )
    database = root / "auth/sessions.sqlite3"
    with ops.maintenance(root):
        before = database.read_bytes()
        with pytest.raises(StoreBusy), staging_app(config):
            pytest.fail("A server must not start during maintenance.")
        assert database.read_bytes() == before


def test_legacy_server_and_export_observers_are_also_fenced(store):
    root, identity, _ = store
    export = root / "workspaces" / identity["workspace_id"] / "exports" / ("a" * 32)
    export.mkdir()
    for path in (root / ".staging-server.lock", export / ".observer.lock"):
        with (
            FileLock(
                path, mode=0o600 if path.name == ".staging-server.lock" else 0o644
            ),
            pytest.raises(StoreBusy),
            ops.maintenance(root),
        ):
            pytest.fail("An existing legacy writer must block maintenance.")
    with (
        ops.maintenance(root),
        pytest.raises(Timeout),
        FileLock(export / ".observer.lock", timeout=0),
    ):
        pytest.fail("The known export observer must remain fenced.")


def test_late_export_cannot_even_create_its_folder_during_maintenance(
    store, monkeypatch
):
    root, identity, _ = store
    workspace = root / "workspaces" / identity["workspace_id"]
    folder = workspace / "exports" / ("b" * 32)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sequence",
            "--project",
            str(folder / "project.json"),
            "--jobs",
            str(workspace / "jobs"),
            "--directory",
            str(folder),
            "--resource-root",
            str(root / ".workspaces-resources"),
        ],
    )
    monkeypatch.setattr(
        sequence, "assemble", lambda *a: pytest.fail("No assembly while maintaining.")
    )
    with ops.maintenance(root):
        assert sequence.main() == 75
        assert not folder.exists()


def test_completed_history_does_not_hold_one_descriptor_per_export(store):
    root, identity, _ = store
    exports = root / "workspaces" / identity["workspace_id"] / "exports"
    for number in range(100):
        export = exports / f"{number:032x}"
        export.mkdir()
        (export / "state.json").write_text(
            json.dumps({"status": "succeeded" if number % 2 else "failed"})
        )
    pending = exports / ("f" * 32)
    pending.mkdir()
    (pending / "state.json").write_text('{"status": "queued"}')
    with ops.maintenance(root) as descriptors:
        assert len(descriptors) == 3
        with pytest.raises(Timeout), FileLock(pending / ".observer.lock", timeout=0):
            pytest.fail("An unresolved legacy startup must retain its observer fence.")


def test_child_keeps_store_busy_after_parent_writer_releases_it(store):
    root = store[0]
    code = "from pathlib import Path; import signal,sys; from aipg_cinema.store_activity import store_activity;\nwith store_activity(Path(sys.argv[1])):\n print('ready', flush=True); signal.pause()"
    with store_activity(root):
        child = subprocess.Popen(
            [sys.executable, "-c", code, str(root)], stdout=subprocess.PIPE, text=True
        )
        try:
            assert select.select([child.stdout], [], [], 10)[0]
            assert child.stdout.readline().strip() == "ready"
        except BaseException:
            child.terminate()
            child.wait(timeout=10)
            raise
    try:
        assert child.poll() is None
        with pytest.raises(StoreBusy), ops.maintenance(root):
            pytest.fail("A surviving child is still a writer.")
    finally:
        child.terminate()
        child.wait(timeout=10)
        child.stdout.close()
    with ops.maintenance(root):
        pass


def test_exec_maintenance_retains_fence_in_foreground_command(store):
    root = store[0]
    code = "import signal; print('ready', flush=True); signal.pause()"
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "aipg_cinema.maintenance",
            "hold",
            "--state-dir",
            str(root),
            "--",
            sys.executable,
            "-c",
            code,
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert select.select([child.stdout], [], [], 10)[0]
        assert child.stdout.readline().strip() == "ready"
        assert child.poll() is None
        with pytest.raises(StoreBusy), store_activity(root):
            pytest.fail("The foreground command must retain maintenance.")
        with pytest.raises(StoreBusy), file_lease(root / ".staging-server.lock"):
            pytest.fail("The compatibility fence must survive exec too.")
    finally:
        child.terminate()
        child.wait(timeout=10)
        child.stdout.close()
    with ops.maintenance(root):
        pass


def test_restore_preserves_ownership_projects_but_requires_fresh_sign_in(
    store, tmp_path_factory
):
    root, identity, project = store
    clone = clone_store(root, tmp_path_factory)
    before = (
        clone
        / "workspaces"
        / identity["workspace_id"]
        / "projects"
        / project["id"]
        / "project.json"
    ).read_bytes()
    ops.prepare_restore(clone, root)
    assert (
        clone
        / "workspaces"
        / identity["workspace_id"]
        / "projects"
        / project["id"]
        / "project.json"
    ).read_bytes() == before
    assert json.loads((clone / ".workspaces-resources/policy.json").read_text())[
        "workspaces"
    ] == str(clone / "workspaces")
    with sqlite3.connect(clone / "auth/sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM login_flows").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT workspace FROM account_workspaces WHERE account=?",
                (identity["account_id"],),
            ).fetchone()[0]
            == identity["workspace_id"]
        )

    def authority(request):
        if request.url.path.endswith("/auth/google/exchange"):
            return httpx.Response(
                200,
                json={
                    "account_id": identity["account_id"],
                    "access_token": "new-test-only-token",
                    "token_type": "Bearer",
                    "expires_in": 900,
                },
            )
        assert request.url.path.endswith("/account/ownership")
        return httpx.Response(
            200, json={"account_id": identity["account_id"], "account_aliases": []}
        )

    core = CoreAccounts("test-only-key", transport=httpx.MockTransport(authority))
    try:
        accounts = AccountSessions(
            clone / "auth", core, origin="https://studio.example"
        )
        with pytest.raises(SessionError):
            accounts.resolve("a" * 43)
        app = create_hosted_app(
            accounts,
            clone / "workspaces",
            origin=accounts.origin,
            google_client_id="public-client",
        )
        with TestClient(app, base_url=accounts.origin) as client:
            recovered = google(client).json()
            assert recovered["workspace_id"] == identity["workspace_id"]
            assert client.get(f"/api/projects/{project['id']}").json() == project
    finally:
        core.close()
    with sqlite3.connect(root / "auth/sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1


@pytest.mark.parametrize(
    "mode", ["original", "nested", "wrong-source", "already-prepared"]
)
def test_restore_never_invalidates_original_or_already_live_store(
    store, tmp_path_factory, mode
):
    root = store[0]
    clone = clone_store(root, tmp_path_factory)
    if mode == "already-prepared":
        ops.prepare_restore(clone, root)
    destination = root if mode == "original" else clone
    previous = clone.parent if mode == "nested" else root
    if mode == "wrong-source":
        previous = root.parent / "other-source"
    database = destination / "auth/sessions.sqlite3"
    before = database.read_bytes()
    with pytest.raises(ValueError):
        ops.prepare_restore(destination, previous)
    assert database.read_bytes() == before


@pytest.mark.parametrize("damage", ["policy", "symlink", "schema", "trigger"])
def test_invalid_restored_data_fails_before_sessions_are_cleared(
    store, tmp_path_factory, damage
):
    root, identity, _ = store
    clone = clone_store(root, tmp_path_factory)
    if damage == "policy":
        path = clone / ".workspaces-resources/policy.json"
        value = json.loads(path.read_text())
        value["transfer_peak_bytes"]["import"] += 1
        path.write_text(json.dumps(value))
    elif damage == "symlink":
        (clone / "workspaces" / identity["workspace_id"] / "outside").symlink_to(root)
    else:
        with sqlite3.connect(clone / "auth/sessions.sqlite3") as db:
            db.execute(
                "ALTER TABLE sessions ADD COLUMN unexpected TEXT"
                if damage == "schema"
                else "CREATE TRIGGER unsafe AFTER DELETE ON sessions BEGIN DELETE FROM account_workspaces; END"
            )
    before = (clone / "auth/sessions.sqlite3").read_bytes()
    with pytest.raises(ValueError):
        ops.prepare_restore(clone, root)
    assert (clone / "auth/sessions.sqlite3").read_bytes() == before


def test_failed_policy_rebind_keeps_relocated_store_unstartable_until_retry(
    store, tmp_path_factory, monkeypatch
):
    root, _, _ = store
    clone = clone_store(root, tmp_path_factory)
    policy = clone / ".workspaces-resources/policy.json"
    before = policy.read_bytes()
    original_write = ops.atomic_json

    def unavailable(*args, **kwargs):
        raise OSError("private disk detail")

    monkeypatch.setattr(ops, "atomic_json", unavailable)
    with pytest.raises(OSError):
        ops.prepare_restore(clone, root)
    assert policy.read_bytes() == before
    with sqlite3.connect(clone / "auth/sessions.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    key = clone.parent / (clone.name + "-test-key")
    key.write_text("test-only-key")
    key.chmod(0o600)
    config = StagingConfig(
        clone, key, "https://studio.example", "public-client", "a" * 64
    )
    with pytest.raises(ValueError, match="policy differs"), staging_app(config):
        pytest.fail("A half-prepared restore must not serve.")
    monkeypatch.setattr(ops, "atomic_json", original_write)
    ops.prepare_restore(clone, root)
    with staging_app(config):
        pass


def test_unknown_export_metadata_fails_closed_without_type_traceback(store, capsys):
    root, identity, _ = store
    folder = root / "workspaces" / identity["workspace_id"] / "exports" / ("f" * 32)
    folder.mkdir()
    (folder / "state.json").write_text('{"status": {"untrusted": "value"}}')
    with pytest.raises(SystemExit) as error:
        ops.main(["hold", "--state-dir", str(root), "--", "must-not-execute"])
    assert error.value.code == 1
    output = capsys.readouterr().err
    assert "Store maintenance rejected" in output
    assert "Traceback" not in output
