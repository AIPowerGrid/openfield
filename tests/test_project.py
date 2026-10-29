import json
import os
import select
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aipg_cinema import app
from aipg_cinema.contracts import TakeDraft, TakeRequest
from aipg_cinema.project import Conflict, NewProject, Project, ProjectStore, Shot


def test_store_reopens_structures_and_keeps_revision_conflicts(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create(NewProject(title="Paper boat", frame_format="square"))
    assert [shot.beat for shot in project.shots] == ["hook", "reveal", "payoff"]
    assert project.frames == 360
    assert all(shot.draft.frame_format == "square" for shot in project.shots)
    stale = project.model_copy(deep=True)
    project.shots.reverse()
    project.shots[0].trim_start = 24
    saved = store.save(project)
    assert saved.revision == 1
    assert ProjectStore(tmp_path).load(project.id) == saved
    assert store.list() == [saved]
    with pytest.raises(Conflict):
        store.save(stale)
    assert store.load(project.id) == saved
    assert not list((tmp_path / project.id).glob(".saving-*"))


def test_two_store_instances_cannot_overwrite_the_same_revision(tmp_path):
    first, second = ProjectStore(tmp_path), ProjectStore(tmp_path)
    original = first.create(NewProject())

    def save(store):
        try:
            return store.save(original).revision
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, (first, second)))
    assert sorted(map(str, results)) == ["1", "conflict"]
    assert first.load(original.id).revision == 1


def test_project_creation_request_reopens_current_project_without_replacing_edits(
    tmp_path,
):
    request = NewProject(title="One short", frame_format="square")
    first = ProjectStore(tmp_path)
    created = first.create(request, request_id="c" * 32)
    assert created.id == "c" * 32
    created.title = "A later edit"
    created.shots[0].draft.prompt = "Keep this later scene"
    updated = first.save(created)
    second = ProjectStore(tmp_path)
    assert second.create(request, request_id="c" * 32) == updated
    original, reopened = second.creation("c" * 32)
    assert original == request and reopened == updated
    assert second.list() == [updated]
    assert not list(tmp_path.glob(".creating-*"))


@pytest.mark.parametrize(
    "changed",
    [
        {"title": "Different short"},
        {"frame_format": "portrait"},
        {"structure": "blank"},
    ],
)
def test_project_creation_id_cannot_be_reused_for_new_details(tmp_path, changed):
    store = ProjectStore(tmp_path)
    body = NewProject(title="Original", frame_format="square")
    project = store.create(body, request_id="b" * 32)
    with pytest.raises(Conflict):
        store.create(body.model_copy(update=changed), request_id="b" * 32)
    assert store.load(project.id) == project
    assert store.list() == [project]


def test_parallel_creation_requests_only_publish_one_project(tmp_path):
    request = NewProject(title="One request", structure="before-after")

    def create(_):
        return ProjectStore(tmp_path).create(request, request_id="a" * 32)

    with ThreadPoolExecutor(max_workers=4) as pool:
        projects = list(pool.map(create, range(4)))
    assert all(project == projects[0] for project in projects)
    assert ProjectStore(tmp_path).list() == projects[:1]


def test_separate_processes_recover_identical_creation_and_shot_ids(tmp_path):
    if os.name != "posix":
        pytest.skip(
            "Pipe readiness is POSIX-only; threaded creation is tested separately."
        )
    code = """import sys,time
from pathlib import Path
from aipg_cinema import project
original=project.atomic_json
def write(path,value):
 if path.name=='project.json': time.sleep(.1)
 original(path,value)
project.atomic_json=write
print('ready',flush=True)
sys.stdin.readline()
saved=project.ProjectStore(Path(sys.argv[1])).create(project.NewProject(title='Same request'),request_id='a'*32)
print(saved.model_dump_json(),flush=True)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", os.defpath)},
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            assert select.select([child.stdout], [], [], 5)[0]
            assert child.stdout.readline() == b"ready\n"
        for child in children:
            child.stdin.write(b"create\n")
            child.stdin.flush()
        results = []
        for child in children:
            assert select.select([child.stdout], [], [], 5)[0]
            results.append(json.loads(child.stdout.readline()))
            child.communicate(timeout=5)
            assert child.returncode == 0
        assert results[0] == results[1]
        assert [p.model_dump() for p in ProjectStore(tmp_path).list()] == results[:1]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


def test_atomic_creation_failure_leaves_no_partial_project_or_receipt(
    tmp_path, monkeypatch
):
    from aipg_cinema import project as project_module

    original = project_module.atomic_json

    def fail(path, value):
        if path.name == "project.json":
            assert ProjectStore(tmp_path).list() == []
            raise OSError("Disk write failed")
        return original(path, value)

    monkeypatch.setattr(project_module, "atomic_json", fail)
    store = ProjectStore(tmp_path)
    with pytest.raises(OSError):
        store.create(NewProject(), request_id="d" * 32)
    assert store.list() == []
    with pytest.raises(FileNotFoundError):
        store.creation("d" * 32)
    assert not list(tmp_path.glob(".creating-*"))
    monkeypatch.setattr(project_module, "atomic_json", original)
    assert store.create(NewProject(), request_id="d" * 32).id == "d" * 32


def test_project_listing_ignores_incomplete_staging_before_inspecting_files(tmp_path):
    staging = tmp_path / ".creating-interrupted"
    staging.mkdir()
    (staging / "project.json").symlink_to(tmp_path / "missing.json")
    assert ProjectStore(tmp_path).list() == []


@pytest.mark.parametrize(
    "update",
    [
        {"trim_start": 100, "trim_end": 80},
        {"trim_end": 121},
        {"trim_start": 0.5},
        {"volume": float("nan")},
        {"volume": 3},
        {"selected_take_id": "../../private"},
        {"beat": "execute"},
    ],
)
def test_shot_rejects_invalid_edits(update):
    with pytest.raises(ValidationError):
        Shot.model_validate(update)


def test_project_rejects_ambiguous_ids_formats_and_excess_shots():
    shot = Shot(draft=TakeDraft(mode="text", frame_format="portrait"))
    for shots in ([shot, shot], [shot] * 7, [Shot()]):
        with pytest.raises(ValidationError):
            Project(id="a" * 32, shots=shots)


def test_shared_direction_is_resolved_once_without_mutating_the_draft(tmp_path):
    store = ProjectStore(tmp_path)
    project = store.create(NewProject())
    project.art_direction = "Paper-cut miniature world."
    shot = project.shots[0]
    shot.draft.prompt = "The boat turns toward a lighthouse."
    original = project.model_dump()
    request = project.request(shot.id, "b" * 32)
    assert (
        request.prompt
        == "Paper-cut miniature world.\n\nThe boat turns toward a lighthouse."
    )
    assert request.shared_direction == project.art_direction
    assert request.project_revision == 0
    assert request.shot_id == shot.id
    assert project.model_dump() == original
    shot.direction_override = "Watercolor."
    assert project.request(shot.id, "b" * 32).prompt.startswith("Watercolor.\n\n")
    shot.direction_override = ""
    assert project.request(shot.id, "b" * 32).prompt == shot.draft.prompt
    shot.draft.prompt = ""
    with pytest.raises(ValueError, match="Describe"):
        project.request(shot.id, "b" * 32)


def test_take_cannot_claim_incomplete_project_context():
    for context in (
        {"project_id": "a" * 32},
        {"shot_id": "a" * 32},
        {"project_revision": 1},
        {"shared_direction": "style"},
    ):
        with pytest.raises(ValidationError):
            TakeRequest(request_id="b" * 32, mode="text", prompt="A boat", **context)


@pytest.fixture
def studio(tmp_path, monkeypatch):
    processes = []
    monkeypatch.setenv("COMFY_BASE_URL", "http://127.0.0.1:18291")
    monkeypatch.setenv("COMFY_UPSTREAM_URL", "http://127.0.0.1:18189")
    monkeypatch.setattr(
        app.httpx,
        "get",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"devices": []}),
    )

    @contextmanager
    def client(*args, **kwargs):
        yield None

    monkeypatch.setattr(app, "sdk_client", client)

    class Process:
        returncode = None

        def __init__(self, args, **kwargs):
            self.args = args
            processes.append(self)

        def poll(self):
            return self.returncode

    monkeypatch.setattr(app.subprocess, "Popen", Process)
    web = TestClient(
        app.create_app(tmp_path, "self-hosted", 20), base_url="http://localhost"
    )
    return web, tmp_path, processes


def test_http_saved_board_reorders_duplicates_and_selects_without_inference(studio):
    web, root, processes = studio
    project = web.post(
        "/api/projects", json={"title": "A short", "frame_format": "square"}
    ).json()
    original_shots = [shot["id"] for shot in project["shots"]]
    project["shots"].reverse()
    duplicate = {**project["shots"][0], "id": "e" * 32, "title": "Alternative ending"}
    project["shots"].append(duplicate)
    response = web.put(f"/api/projects/{project['id']}", json=project)
    assert response.status_code == 200
    saved = response.json()
    assert [s["id"] for s in saved["shots"]] == original_shots[::-1] + ["e" * 32]
    assert web.put(f"/api/projects/{project['id']}", json=project).status_code == 409
    assert web.get(f"/api/projects/{project['id']}").json() == saved
    assert len(web.get("/api/projects").json()) == 1
    assert not processes
    assert not list((root / "jobs").glob("*/request.json"))
    assert web.get("/api/projects/not-a-project").status_code == 404
    assert web.put("/api/projects/" + "a" * 32, json=saved).status_code == 409


def test_http_creation_receipt_recovers_same_short_and_frozen_request(studio):
    web, root, processes = studio
    path = "/api/project-creations/" + "c" * 32
    body = {"title": "One short", "frame_format": "square", "structure": "before-after"}
    assert web.get(path).status_code == 404
    assert web.get("/api/projects").json() == []
    first = web.post(path, json=body)
    assert first.status_code == 200
    receipt = first.json()
    assert receipt["id"] == receipt["project"]["id"] == "c" * 32
    assert receipt["request"] == body
    project = receipt["project"]
    project["title"] = "Changed after creation"
    saved = web.put("/api/projects/" + project["id"], json=project).json()
    assert web.post(path, json=body).json()["project"] == saved
    assert web.get(path).json() == {**receipt, "project": saved}
    assert len(web.get("/api/projects").json()) == 1
    assert web.post(path, json={**body, "title": "Another short"}).status_code == 409
    assert web.get("/api/projects/" + project["id"]).json() == saved
    assert web.get("/api/project-creations/not-an-id").status_code == 404
    assert not processes and not list((root / "jobs").glob("*/request.json"))


def test_creation_cannot_overwrite_a_legacy_or_imported_project(studio):
    web, _root, processes = studio
    existing = web.post("/api/projects", json={"title": "Existing"}).json()
    path = "/api/project-creations/" + existing["id"]
    assert web.get(path).status_code == 404
    assert web.post(path, json={"title": "Replacement"}).status_code == 409
    assert web.get("/api/projects/" + existing["id"]).json() == existing
    assert not processes


def test_creation_error_after_publication_remains_recoverable(studio, monkeypatch):
    from aipg_cinema import project as project_module

    web, root, processes = studio
    original = project_module._directory_sync

    def fail_after_publish(path):
        if path == root / "projects":
            raise OSError("Private disk detail must not reach the browser")
        original(path)

    monkeypatch.setattr(project_module, "_directory_sync", fail_after_publish)
    path = "/api/project-creations/" + "e" * 32
    response = web.post(path, json={"title": "Published before failure"})
    assert response.status_code == 503
    assert "Private disk detail" not in response.text
    receipt = web.get(path)
    assert receipt.status_code == 200
    assert receipt.json()["project"]["title"] == "Published before failure"
    assert len(web.get("/api/projects").json()) == 1
    assert not processes


def test_shot_board_script_and_icons_ship_in_the_app(studio):
    web, _root, processes = studio
    assert "/board.js" in web.get("/").text
    response = web.get("/board.js")
    assert response.status_code == 200 and "generateBoardShot" in response.text
    for icon in ("plus", "arrow-left", "arrow-right", "trash-2", "save", "check"):
        response = web.get(f"/icons/{icon}.svg")
        assert response.status_code == 200 and "<svg" in response.text
    assert not processes


def test_http_render_pins_one_shot_and_replay_survives_later_project_edits(studio):
    web, root, processes = studio
    project = web.post("/api/projects", json={"frame_format": "square"}).json()
    project["art_direction"] = "Handmade paper."
    project["shots"][0]["draft"]["prompt"] = "A boat enters the frame."
    project = web.put(f"/api/projects/{project['id']}", json=project).json()
    shot = project["shots"][0]
    url = f"/api/projects/{project['id']}/shots/{shot['id']}/generate"
    body = {"request_id": "b" * 32, "revision": project["revision"]}
    response = web.post(url, json=body)
    assert response.status_code == 200
    take = response.json()
    assert take["prompt"] == "Handmade paper.\n\nA boat enters the frame."
    assert take["project_id"] == project["id"] and take["shot_id"] == shot["id"]
    assert len(processes) == 1
    arguments = processes[0].args
    assert f"--prompt={take['prompt']}" in arguments
    snapshot = (root / "jobs" / body["request_id"] / "request.json").read_bytes()
    project["art_direction"] = "Different art direction."
    changed = web.put(f"/api/projects/{project['id']}", json=project).json()
    assert web.post(url, json=body).status_code == 200
    assert len(processes) == 1
    assert (
        root / "jobs" / body["request_id"] / "request.json"
    ).read_bytes() == snapshot
    assert web.post(url, json={**body, "request_id": "c" * 32}).status_code == 409
    forged = {key: take[key] for key in TakeRequest.model_fields}
    forged.update(
        request_id="d" * 32,
        project_revision=changed["revision"],
        prompt="Unreviewed prompt",
    )
    assert web.post("/api/jobs", json=forged).status_code == 409
    assert len(processes) == 1
    settings = web.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["project_revision"] == body["revision"]
    assert settings["shared_direction"] == "Handmade paper."


def test_selecting_a_completed_take_is_explicit_and_format_checked(studio):
    web, root, processes = studio
    project = web.post("/api/projects", json={"frame_format": "square"}).json()
    project["shots"][0]["selected_take_id"] = "a" * 32
    assert web.put(f"/api/projects/{project['id']}", json=project).status_code == 404
    folder = root / "jobs" / ("a" * 32)
    folder.mkdir()
    request = TakeRequest(
        request_id="a" * 32, mode="text", prompt="A boat", frame_format="square"
    )
    (folder / "request.json").write_text(request.model_dump_json())
    assert web.put(f"/api/projects/{project['id']}", json=project).status_code == 409
    (folder / "render").mkdir()
    (folder / "render" / "reshoot.mp4").write_bytes(b"completed fixture")
    response = web.put(f"/api/projects/{project['id']}", json=project)
    assert response.status_code == 200
    assert response.json()["shots"][0]["selected_take_id"] == "a" * 32
    request.frame_format = "portrait"
    (folder / "request.json").write_text(request.model_dump_json())
    assert (
        web.put(f"/api/projects/{project['id']}", json=response.json()).status_code
        == 409
    )
    assert not processes


@pytest.mark.parametrize(
    "kind", ["malformed", "incomplete-context", "wrong-identity", "unreadable"]
)
def test_invalid_selected_take_cannot_overwrite_a_saved_project(
    studio, monkeypatch, kind
):
    from pathlib import Path

    web, root, processes = studio
    project = web.post("/api/projects", json={"frame_format": "square"}).json()
    original = json.loads(json.dumps(project))
    folder = root / "jobs" / ("a" * 32)
    (folder / "render").mkdir(parents=True)
    request = TakeRequest(
        request_id="a" * 32,
        mode="text",
        prompt="Original fixture",
        frame_format="square",
    ).model_dump()
    if kind == "incomplete-context":
        request["project_id"] = project["id"]
    elif kind == "wrong-identity":
        request["request_id"] = "b" * 32
    request_file = folder / "request.json"
    request_file.write_text("not-json" if kind == "malformed" else json.dumps(request))
    (folder / "render/reshoot.mp4").write_bytes(b"completed fixture")
    if kind == "unreadable":
        read_text = Path.read_text

        def unavailable(path, *args, **kwargs):
            if path == request_file:
                raise OSError("private-storage-detail")
            return read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", unavailable)
    for shot in project["shots"]:
        shot["selected_take_id"] = "a" * 32
    response = web.put(f"/api/projects/{project['id']}", json=project)
    assert response.status_code == (503 if kind == "unreadable" else 409)
    assert "private-storage-detail" not in response.text
    assert web.get(f"/api/projects/{project['id']}").json() == original
    assert not processes


def test_removed_shot_does_not_delete_its_immutable_take(studio):
    web, root, processes = studio
    project = web.post("/api/projects", json={}).json()
    project["shots"][0]["draft"]["prompt"] = "A boat"
    project = web.put(f"/api/projects/{project['id']}", json=project).json()
    shot = project["shots"][0]
    assert (
        web.post(
            f"/api/projects/{project['id']}/shots/{shot['id']}/generate",
            json={"request_id": "a" * 32, "revision": project["revision"]},
        ).status_code
        == 200
    )
    project["shots"].pop(0)
    assert web.put(f"/api/projects/{project['id']}", json=project).status_code == 200
    assert (
        json.loads((root / "jobs" / ("a" * 32) / "request.json").read_text())["shot_id"]
        == shot["id"]
    )
    assert len(processes) == 1


def test_export_freezes_revision_is_idempotent_and_never_calls_inference(studio):
    web, root, processes = studio
    project = web.post("/api/projects", json={"frame_format": "square"}).json()
    folder = root / "jobs" / ("a" * 32)
    (folder / "render").mkdir(parents=True)
    (folder / "request.json").write_text(
        TakeRequest(
            request_id="a" * 32, mode="text", prompt="A boat", frame_format="square"
        ).model_dump_json()
    )
    (folder / "render" / "reshoot.mp4").write_bytes(b"completed test fixture")
    url = f"/api/projects/{project['id']}/exports"
    body = {"request_id": "e" * 32, "revision": project["revision"]}
    assert web.post(url, json=body).status_code == 400
    for shot in project["shots"]:
        shot["selected_take_id"] = "a" * 32
    project = web.put(f"/api/projects/{project['id']}", json=project).json()
    body["revision"] = project["revision"]
    response = web.post(url, json=body)
    assert response.status_code == 200
    assert response.json()["active"] is True
    assert response.json()["status"] == "queued"
    assert len(processes) == 1
    assert processes[0].args[2] == "aipg_cinema.sequence"
    assert processes[0].args[-2:] == ["--audio-root", str(root / "audio")]
    assert "--execute" not in processes[0].args and "--backend" not in processes[0].args
    frozen = root / "exports" / body["request_id"] / "project.json"
    (frozen.parent / "state.json").write_text('{"status":"running"}')
    assert web.get(f"/api/exports/{body['request_id']}").json()["status"] == "running"
    original = frozen.read_bytes()
    project["title"] = "A changed title"
    assert web.put(f"/api/projects/{project['id']}", json=project).status_code == 200
    assert web.post(url, json=body).status_code == 200
    assert len(processes) == 1 and frozen.read_bytes() == original
    assert (
        web.post(url, json={**body, "revision": project["revision"] + 1}).status_code
        == 409
    )
    assert len(web.get(url).json()) == 1
    processes[0].returncode = 1
    assert (
        web.get(f"/api/exports/{body['request_id']}").json()["status"]
        == "needs_recovery"
    )
    assert web.post(f"/api/exports/{body['request_id']}/resume").status_code == 200
    assert len(processes) == 2
    assert frozen.read_bytes() == original
    processes[1].returncode = 0
    (frozen.parent / "short.mp4").write_bytes(b"finished fixture")
    (frozen.parent / "manifest.json").write_text("{}")
    assert web.get(f"/api/exports/{body['request_id']}").json()["status"] == "succeeded"
    assert (
        web.get(f"/api/exports/{body['request_id']}/output").content
        == b"finished fixture"
    )
    assert web.get(f"/api/exports/{body['request_id']}/../.env").status_code == 404
    assert (
        web.get(f"/api/exports/{body['request_id']}/preview").content
        == b"finished fixture"
    )


def test_export_captions_are_frozen_and_clean_preview_is_distinct(studio):
    web, root, processes = studio
    project = web.post("/api/projects", json={"frame_format": "square"}).json()
    take = root / "jobs" / ("a" * 32)
    (take / "render").mkdir(parents=True)
    (take / "request.json").write_text(
        TakeRequest(
            request_id="a" * 32, mode="text", prompt="A boat", frame_format="square"
        ).model_dump_json()
    )
    (take / "render/reshoot.mp4").write_bytes(b"selected fixture")
    for shot in project["shots"]:
        shot["selected_take_id"] = "a" * 32
    cue = {
        "id": "c" * 32,
        "text": "Original caption",
        "start_frame": 0,
        "end_frame": 48,
    }
    project["captions"] = [
        cue,
        {**cue, "id": "d" * 32, "start_frame": 24, "end_frame": 72},
    ]
    url = f"/api/projects/{project['id']}"
    project = web.put(url, json=project).json()
    body = {"request_id": "e" * 32, "revision": project["revision"]}
    assert web.post(url + "/exports", json=body).status_code == 400
    assert not processes and not (root / "exports" / body["request_id"]).exists()
    project["captions"] = project["captions"][:1]
    project = web.put(url, json=project).json()
    body["revision"] = project["revision"]
    assert web.post(url + "/exports", json=body).status_code == 200
    folder = root / "exports" / body["request_id"]
    assert json.loads((folder / "project.json").read_text())["captions"] == [cue]
    assert web.get(f"/api/exports/{body['request_id']}/preview").status_code == 404
    processes[0].returncode = 0
    (folder / "short.mp4").write_bytes(b"burned captions")
    # Never preview a captioned video with a second live overlay on top.
    assert web.get(f"/api/exports/{body['request_id']}").json()["preview_url"] is None
    (folder / "picture.mp4").write_bytes(b"clean picture")
    (folder / "captions.srt").write_text("timed text")
    item = web.get(f"/api/exports/{body['request_id']}").json()
    assert web.get(item["preview_url"]).content == b"clean picture"
    assert web.get(item["output_url"]).content == b"burned captions"
    assert web.get(item["captions_url"]).text == "timed text"
