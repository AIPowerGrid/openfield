import hashlib
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_auth import google
from test_finishing import sound
from test_sequence import media  # noqa: F401 -- shared encoded-media fixture

from aipg_cinema import app, portable, sequence
from aipg_cinema.assets import asset_folder, asset_records
from aipg_cinema.contracts import LookRequest, TakeDraft, TakeRequest
from aipg_cinema.generation import graph
from aipg_cinema.look import graph as look_graph
from aipg_cinema.project import (
    AudioLayer,
    Caption,
    LookAudition,
    NewProject,
    ProjectStore,
)


@pytest.fixture(scope="module")
def package_fixture(media, tmp_path_factory):  # noqa: F811 -- imported pytest fixture
    workspace = tmp_path_factory.mktemp("portable-source")
    shutil.copytree(media, workspace / "jobs")
    store = ProjectStore(workspace / "projects")
    project = store.create(
        NewProject(title="Original boat board", frame_format="square")
    )
    project.art_direction = "Neon puddles and paper boats."
    image_id, generated_id, source_id = "d" * 32, "e" * 32, "f" * 32
    images = workspace / "looks"
    (images / image_id).mkdir(parents=True)
    Image.new("RGB", (1280, 1280), "red").save(images / image_id / "look.png")
    (images / image_id / "upload.json").write_text('{"frame_format":"square"}')
    source = workspace / "sources" / source_id
    source.mkdir(parents=True)
    shutil.copyfile(
        media / f"{1:032x}" / "render" / "reshoot.mp4", source / "source.mp4"
    )
    (source / "source.json").write_text('{"name":"Original source.mp4"}')
    generated = images / generated_id
    (generated / "render").mkdir(parents=True)
    request = LookRequest(
        request_id=generated_id,
        look_input="image",
        image_id=image_id,
        prompt="A copper boat",
        frame_format="square",
        audition=True,
        project_id=project.id,
        shot_id=project.shots[0].id,
        project_revision=0,
    )
    (generated / "request.json").write_text(
        json.dumps({**request.model_dump(), "engine": "moss"})
    )
    shutil.copyfile(images / image_id / "look.png", generated / "render" / "look.png")
    shutil.copyfile(images / image_id / "look.png", generated / "render" / "source.png")
    (generated / "render" / "workflow.json").write_text(
        json.dumps(look_graph("A copper boat", frame_format="square"))
    )
    for index, shot in enumerate(project.shots, 1):
        folder = workspace / "jobs" / f"{index:032x}"
        take = TakeRequest(
            request_id=folder.name,
            mode="text",
            prompt="A boat crosses the puddle",
            frame_format="square",
            project_id=project.id,
            shot_id=shot.id,
            project_revision=0,
            shared_direction=project.art_direction,
        )
        if index == 1:
            take.mode, take.look_id, take.closing_id = "image", image_id, image_id
            for filename in ("look.png", "closing.png"):
                shutil.copyfile(
                    images / image_id / "look.png", folder / "render" / filename
                )
        (folder / "request.json").write_text(take.model_dump_json())
        (folder / "render" / "workflow.json").write_text(
            json.dumps(
                graph(
                    take.prompt,
                    mode=take.mode,
                    frame_format="square",
                    opening=bool(take.look_id),
                    closing=bool(take.closing_id),
                )
            )
        )
        (folder / "render" / "job.json").write_text(
            '{"job_id":"private-provider-job","base_url":"http://private-worker:8188","api_key":"do-not-export-secret"}'
        )
        shot.selected_take_id = take.request_id
        shot.draft = TakeDraft.model_validate(
            {k: v for k, v in take.model_dump().items() if k in TakeDraft.model_fields}
        )
    project.shots[0].audition = LookAudition(
        input_key=json.dumps(["image", None, 0, "square"]),
        reference_id=image_id,
        left_id=generated_id,
        right_id=image_id,
        direction="Compare copper",
    )
    project.shots[1].draft = TakeDraft(
        mode="video",
        source_id=source_id,
        frame_format="square",
        prompt="Keep the motion",
    )
    project.shots[1].audition = LookAudition(
        input_key=json.dumps(["video", source_id, 0, "square"]),
        direction="Refine this source frame",
    )
    sound(workspace / "audio", seconds=6)
    project.shots[2].draft = TakeDraft(
        mode="audio", audio_id="b" * 32, frame_format="square", prompt="Follow the beat"
    )
    project.shots[2].audition = LookAudition(
        input_key=json.dumps(["audio", "b" * 32, 0, "square"]),
        reference_id=image_id,
        direction="Audio scene reference",
    )
    project.music = AudioLayer(
        audio_id="b" * 32, duration_frames=360, loop=True, volume=0.2
    )
    project.captions = [Caption(text="ORIGINAL", start_frame=0, end_frame=24)]
    project = store.save(project)
    (workspace / ".env").write_text("SERVICE_KEY=do-not-export-secret")
    archive = portable.export_project(workspace, project, workspace / "board.aipg.zip")
    return workspace, project, archive


def rewrite(archive, destination, transform):
    with zipfile.ZipFile(archive) as original:
        files = {name: original.read(name) for name in original.namelist()}
    package = json.loads(files["project.json"])
    transform(package, files)
    files["project.json"] = json.dumps(package).encode()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data in files.items():
            output.writestr(name, data)
    return destination


def test_archive_writer_checks_growth_before_writing_and_allows_header_rewrites(
    tmp_path,
):
    destination = tmp_path / "bounded.zip"
    with portable.BoundedArchive(destination.open("xb", buffering=0), 16) as output:
        output.write(b"x" * 16)
        with pytest.raises(ValueError, match="archive limit"):
            output.write(b"y")
        output.seek(0)
        output.write(b"head")
        output.seek(16)
        with pytest.raises(ValueError, match="archive limit"):
            output.write(b"z")
    assert destination.read_bytes() == b"head" + b"x" * 12


def test_export_rejects_excess_manifest_before_publishing(
    package_fixture, tmp_path, monkeypatch
):
    workspace, project, _ = package_fixture
    monkeypatch.setattr(portable, "MAX_MANIFEST", 1)
    destination = tmp_path / "oversized.aipg.zip"
    with pytest.raises(ValueError, match="metadata"):
        portable.export_project(workspace, project, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".packaging-*"))


def test_export_archive_growth_stops_at_cap(package_fixture, tmp_path, monkeypatch):
    workspace, project, _ = package_fixture
    original = portable.BoundedArchive
    observed = []

    class TrackedArchive(original):
        def write(self, value):
            result = super().write(value)
            observed.append(self.tell())
            return result

    monkeypatch.setattr(portable, "MAX_ARCHIVE", 1024)
    monkeypatch.setattr(portable, "BoundedArchive", TrackedArchive)
    destination = tmp_path / "too-small.aipg.zip"
    with pytest.raises(ValueError, match="archive limit"):
        portable.export_project(workspace, project, destination)
    assert observed and max(observed) <= 1024
    assert not destination.exists()
    assert not list(tmp_path.glob(".packaging-*"))


def test_import_rebuilt_metadata_has_aggregate_budget(
    package_fixture, tmp_path, monkeypatch
):
    _, _, archive = package_fixture
    monkeypatch.setattr(portable, "MAX_REBUILT_METADATA", 64)
    with pytest.raises(ValueError, match="metadata"):
        portable.import_project(tmp_path, archive, "c" * 32)
    assert ProjectStore(tmp_path / "projects").list() == []
    assert not (tmp_path / ".imports" / ("c" * 32 + ".json")).exists()
    assert not list((tmp_path / "projects").glob(".import-*"))


def test_api_frozen_package_metadata_is_bounded_before_publication(
    package_fixture, tmp_path, monkeypatch
):
    _, _, archive = package_fixture
    project = portable.import_project(tmp_path, archive, "d" * 32)
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    monkeypatch.setattr(app, "MAX_MANIFEST_BYTES", 1)
    response = client.post(
        f"/api/projects/{project.id}/packages",
        json={"request_id": "e" * 32, "revision": project.revision},
    )
    assert response.status_code == 400
    assert not (tmp_path / "packages" / ("e" * 32)).exists()
    assert ProjectStore(tmp_path / "projects").load(project.id) == project


def test_complete_roundtrip_retains_edit_references_takes_sound_and_captions(
    package_fixture, tmp_path
):
    _, original, archive = package_fixture
    imported = portable.import_project(tmp_path, archive, "1" * 32)
    assert imported.id != original.id and imported.revision == 0
    assert imported.title == original.title
    assert imported.art_direction == original.art_direction
    assert [s.beat for s in imported.shots] == [s.beat for s in original.shots]
    assert [s.id for s in imported.shots] != [s.id for s in original.shots]
    shot = imported.shots[0]
    assert shot.draft.look_id == shot.draft.closing_id
    assert shot.draft.look_id != original.shots[0].draft.look_id
    assert shot.audition.reference_id == shot.draft.look_id
    assert json.loads(imported.shots[1].audition.input_key) == [
        "video",
        imported.shots[1].draft.source_id,
        0,
        "square",
    ]
    assert json.loads(imported.shots[2].audition.input_key) == [
        "audio",
        imported.shots[2].draft.audio_id,
        0,
        "square",
    ]
    assert imported.captions[0].text == "ORIGINAL"
    assert imported.music.volume == 0.2
    assert imported.shots[2].draft.audio_id == imported.music.audio_id
    assert len(asset_records(tmp_path / "jobs")) == 3
    assert len(asset_records(tmp_path / "looks")) == 1
    output = sequence.assemble(
        imported, tmp_path / "jobs", tmp_path / "export", tmp_path / "audio"
    )
    assert (
        sequence.inspect(output, 1280, 1280, 360, audio_required=True)["seconds"] == 15
    )
    repack = portable.export_project(
        tmp_path, imported, tmp_path / "roundtrip.aipg.zip"
    )
    second = portable.import_project(tmp_path / "second", repack, "2" * 32)
    assert second.title == imported.title
    assert second.shots[0].draft.closing_id == second.shots[0].draft.look_id
    assert second.captions[0].text == imported.captions[0].text
    assert len(asset_records(tmp_path / "second" / "jobs")) == 3


def test_package_excludes_credentials_provider_jobs_unrelated_files_and_hardlinks(
    package_fixture, tmp_path, monkeypatch
):
    _, _, archive = package_fixture
    with zipfile.ZipFile(archive) as package:
        assert all(
            not name.endswith("job.json") and ".env" not in name
            for name in package.namelist()
        )
        assert all(
            b"do-not-export-secret" not in package.read(name)
            and b"private-provider-job" not in package.read(name)
            for name in package.namelist()
        )
    monkeypatch.setattr(
        os, "link", lambda *a, **k: pytest.fail("No hard-link dependency")
    )
    project = portable.import_project(tmp_path, archive, "3" * 32)
    assert not list((tmp_path / "projects" / project.id).rglob("job.json"))
    assert portable.imported_project(tmp_path, "3" * 32) == project
    assert portable.import_project(tmp_path, archive, "3" * 32) == project
    assert len(ProjectStore(tmp_path / "projects").list()) == 1


@pytest.mark.parametrize(
    "defect",
    [
        "extra",
        "missing",
        "checksum",
        "size",
        "version",
        "secret",
        "reference",
        "workflow",
        "path",
    ],
)
def test_malformed_packages_never_publish_projects(package_fixture, tmp_path, defect):
    _, _, archive = package_fixture

    def transform(package, files):
        name = next(iter(package["files"]))
        if defect == "extra":
            files["media/../../escape"] = b"no"
        elif defect == "missing":
            files.pop("media/" + name)
        elif defect == "checksum":
            package["files"][name]["sha256"] = "0" * 64
        elif defect == "size":
            package["files"][name]["size"] += 1
        elif defect == "version":
            package["version"] = 2
        elif defect == "secret":
            package["service_key"] = "forbidden"
        elif defect == "reference":
            package["project"]["shots"][0]["selected_take_id"] = "c" * 32
        elif defect == "path":
            package["files"]["../../outside"] = package["files"].pop(name)
        else:
            name = next(n for n in package["files"] if n.endswith("workflow.json"))
            data = b'{"request":{"class_type":"HTTPRequest","inputs":{"api_key":"secret"}}}'
            files["media/" + name] = data
            package["files"][name] = {
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }

    bad = rewrite(archive, tmp_path / "bad.zip", transform)
    destination = tmp_path / "destination"
    with pytest.raises((ValueError, OSError, zipfile.BadZipFile)):
        portable.import_project(destination, bad, "4" * 32)
    assert not list((destination / "projects").glob("*/project.json"))
    assert not (tmp_path / "escape").exists()
    assert not list((destination / "projects").glob(".import-*"))


@pytest.mark.parametrize("defect", ["duplicate", "symlink", "directory"])
def test_ambiguous_or_nonregular_zip_entries_are_rejected(
    package_fixture, tmp_path, defect
):
    _, _, archive = package_fixture
    bad = tmp_path / "bad.zip"
    shutil.copyfile(archive, bad)
    with zipfile.ZipFile(bad, "a") as output:
        if defect == "duplicate":
            with pytest.warns(UserWarning):
                output.writestr("project.json", b"{}")
        else:
            info = zipfile.ZipInfo("unexpected/" if defect == "directory" else "link")
            info.external_attr = (
                stat.S_IFDIR if defect == "directory" else stat.S_IFLNK
            ) << 16
            output.writestr(info, b"../../outside")
    with pytest.raises(ValueError):
        portable.import_project(tmp_path / "target", bad, "5" * 32)


def test_failure_before_publication_leaves_no_half_project_and_retry_reuses_identity(
    package_fixture, tmp_path, monkeypatch
):
    _, _, archive = package_fixture
    original = Path.rename
    captured = []

    def fail(path, target):
        if path.name == "ready":
            captured.append(target.name)
            assert not (target / "project.json").exists()
            raise OSError("simulated publication interruption")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail)
    with pytest.raises(OSError, match="interruption"):
        portable.import_project(tmp_path, archive, "6" * 32)
    assert not list((tmp_path / "projects").glob("*/project.json"))
    assert portable.imported_project(tmp_path, "6" * 32) is None
    monkeypatch.setattr(Path, "rename", original)
    project = portable.import_project(tmp_path, archive, "6" * 32)
    assert project.id == captured[0]


def test_import_key_cannot_be_rebound_to_different_bytes(package_fixture, tmp_path):
    _, _, archive = package_fixture
    original = portable.import_project(tmp_path, archive, "7" * 32)
    changed = rewrite(
        archive,
        tmp_path / "changed.zip",
        lambda p, f: p["project"].update(title="Different"),
    )
    with pytest.raises(ValueError, match="different project"):
        portable.import_project(tmp_path, changed, "7" * 32)
    assert ProjectStore(tmp_path / "projects").load(original.id) == original


def test_staging_directories_are_not_visible_asset_stores(tmp_path):
    folder = (
        tmp_path / "projects" / ".import-unfinished" / "assets" / "jobs" / ("a" * 32)
    )
    folder.mkdir(parents=True)
    (folder / "request.json").write_text("{}")
    assert asset_records(tmp_path / "jobs") == []
    assert asset_folder(tmp_path / "jobs", "a" * 32) == tmp_path / "jobs" / ("a" * 32)


def test_http_package_download_is_frozen_and_repeatable(package_fixture, tmp_path):
    workspace, project, _ = package_fixture
    root = tmp_path / "workspace"
    shutil.copytree(workspace, root)
    client = TestClient(
        app.create_app(root, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    identity = "8" * 32
    url = f"/api/projects/{project.id}/packages"
    body = {"request_id": identity, "revision": project.revision}
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "complete" and "project" not in receipt
    first = client.get(receipt["download_url"])
    assert (
        first.status_code == 200 and first.headers["content-type"] == "application/zip"
    )
    assert ".aipg.zip" in first.headers["content-disposition"]
    assert client.post(url, json=body).json() == receipt
    assert client.get(receipt["download_url"]).content == first.content
    assert client.post(url, json={**body, "revision": 0}).status_code == 409
    assert client.get("/api/project-packages/" + identity).json() == receipt


def test_http_import_reopens_assets_and_can_be_revised_without_inference(
    package_fixture, tmp_path, monkeypatch
):
    _, original, archive = package_fixture
    monkeypatch.setattr(
        app,
        "sdk_client",
        lambda *a, **k: pytest.fail("Import must not contact a model provider"),
    )
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    url = "/api/project-imports/" + "9" * 32
    response = client.post(
        url, content=archive.read_bytes(), headers={"content-type": "application/zip"}
    )
    assert response.status_code == 200, response.text
    imported = response.json()["project"]
    assert imported["id"] != original.id
    assert client.get(url).json() == response.json()
    assert (
        client.post(
            url,
            content=archive.read_bytes(),
            headers={"content-type": "application/zip"},
        ).json()
        == response.json()
    )
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 3 and all(
        job["status"] == "succeeded" and not job["active"] for job in jobs
    )
    for job in jobs:
        assert client.get(job["output_url"]).status_code == 200
        assert client.get(f"/api/jobs/{job['id']}/workflow").status_code == 200
    assert client.get("/api/config").json()["renders_used"] == 0
    assert len(client.get("/api/look-jobs").json()) == 1
    look = client.get("/api/look-jobs").json()[0]
    assert client.get(f"/api/look-jobs/{look['id']}/settings").json()[
        "negative_skip_layers"
    ] == [22]
    imported["shots"][0]["draft"]["prompt"] = "A revised direction"
    saved = client.put(f"/api/projects/{imported['id']}", json=imported)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert (
        client.get(f"/api/projects/{imported['id']}").json()["shots"][0]["draft"][
            "prompt"
        ]
        == "A revised direction"
    )
    assert client.post("/api/jobs", json={}).status_code == 503


@pytest.mark.parametrize("chunked", [False, True])
def test_import_body_limit_applies_before_zip_parsing_and_cleans_uploads(
    tmp_path, monkeypatch, chunked
):
    monkeypatch.setattr(app, "MAX_ARCHIVE", 32)
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    body = iter([b"x" * 16, b"x" * 17]) if chunked else b"x" * 33
    assert (
        client.post(
            "/api/project-imports/" + "a" * 32,
            content=body,
            headers={"content-type": "application/zip"},
        ).status_code
        == 413
    )
    assert not list((tmp_path / ".project-transfers").glob("*"))
    assert not list((tmp_path / "projects").iterdir())


def test_import_failure_after_atomic_publish_recovers_the_same_project(
    package_fixture, tmp_path, monkeypatch
):
    _, _, archive = package_fixture
    original = portable._sync_directory

    def fail(path):
        if path == tmp_path / "projects":
            raise OSError("response lost after publication")
        original(path)

    monkeypatch.setattr(portable, "_sync_directory", fail)
    with pytest.raises(OSError, match="publication"):
        portable.import_project(tmp_path, archive, "b" * 32)
    existing = portable.imported_project(tmp_path, "b" * 32)
    assert existing is not None
    assert portable.import_project(tmp_path, archive, "b" * 32) == existing
    assert len(ProjectStore(tmp_path / "projects").list()) == 1


def test_archive_directory_metadata_is_bounded_before_entry_allocation(tmp_path):
    archive = tmp_path / "large-directory.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for index in range(2200):
            output.writestr(str(index) + "x" * 250, b"")
    with pytest.raises(ValueError, match="directory metadata"):
        portable.import_project(tmp_path / "target", archive, "c" * 32)


def test_imported_private_packages_cannot_cross_accounts(package_fixture, login_api):
    _, _, archive = package_fixture
    _, _, _, _, open_client = login_api
    first, second = open_client(hosted=True), open_client(hosted=True)
    a, b = google(first).json(), google(second, "proof-b").json()
    url = "/api/project-imports/" + "d" * 32
    response = first.post(
        url,
        content=archive.read_bytes(),
        headers={
            "content-type": "application/zip",
            "origin": "https://studio.example",
            "x-studio-csrf": a["csrf"],
        },
    )
    assert response.status_code == 200, response.text
    project = response.json()["project"]
    assert second.get(url).status_code == 404
    assert second.get(f"/api/projects/{project['id']}").status_code == 404
    assert (
        second.get(
            f"/api/jobs/{project['shots'][0]['selected_take_id']}/output"
        ).status_code
        == 404
    )
    package = first.post(
        f"/api/projects/{project['id']}/packages",
        json={"request_id": "e" * 32, "revision": 0},
        headers={"origin": "https://studio.example", "x-studio-csrf": a["csrf"]},
    )
    assert package.status_code == 200, package.text
    assert second.get(package.json()["download_url"]).status_code == 404
    assert (
        second.post(
            url,
            content=b"no",
            headers={
                "content-type": "application/zip",
                "origin": "https://studio.example",
                "x-studio-csrf": a["csrf"],
            },
        ).status_code
        == 401
    )
    assert b["workspace_id"] != a["workspace_id"]


def test_http_post_publication_io_failure_is_unknown_not_bad_input(
    package_fixture, tmp_path, monkeypatch
):
    _, _, archive = package_fixture
    original = portable._sync_directory

    def fail(path):
        if path == tmp_path / "projects":
            raise OSError("simulated post-publication disk error")
        original(path)

    monkeypatch.setattr(portable, "_sync_directory", fail)
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    url = "/api/project-imports/" + "a" * 32
    response = client.post(
        url, content=archive.read_bytes(), headers={"content-type": "application/zip"}
    )
    assert response.status_code == 503
    recovered = client.get(url)
    assert recovered.status_code == 200 and recovered.json()["status"] == "complete"
    assert (
        client.post(
            url,
            content=archive.read_bytes(),
            headers={"content-type": "application/zip"},
        ).json()
        == recovered.json()
    )
    assert len(client.get("/api/projects").json()) == 1


def test_package_reply_failure_retains_the_completed_download(
    package_fixture, tmp_path, monkeypatch
):
    workspace, project, _ = package_fixture
    root = tmp_path / "workspace"
    shutil.copytree(workspace, root)
    original = app.export_project
    calls = []

    def lost(*args):
        calls.append(True)
        original(*args)
        raise OSError("response lost after complete archive")

    monkeypatch.setattr(app, "export_project", lost)
    client = TestClient(
        app.create_app(root, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    identity = "b" * 32
    url = f"/api/projects/{project.id}/packages"
    body = {"request_id": identity, "revision": project.revision}
    assert client.post(url, json=body).status_code == 503
    receipt = client.get("/api/project-packages/" + identity).json()
    assert receipt["status"] == "complete"
    assert client.post(url, json=body).json() == receipt
    assert client.get(receipt["download_url"]).status_code == 200
    assert calls == [True]


@pytest.mark.parametrize("value", [10**1000, [[], 0], {"untrusted": "value"}])
def test_workflow_validation_rejects_excessive_or_structured_values(tmp_path, value):
    path = tmp_path / "workflow.json"
    path.write_text(
        json.dumps(
            {"seed": {"class_type": "RandomNoise", "inputs": {"noise_seed": value}}}
        )
    )
    with pytest.raises(ValueError):
        portable.validate_workflow(path, set())


def test_stale_audition_input_is_not_rebound_to_a_different_source(
    package_fixture, tmp_path
):
    _, _, archive = package_fixture
    stale = json.dumps(["audio", "0" * 32, 0, "square"])
    changed = rewrite(
        archive,
        tmp_path / "stale.zip",
        lambda p, f: p["project"]["shots"][2]["audition"].update(input_key=stale),
    )
    imported = portable.import_project(tmp_path / "target", changed, "f" * 32)
    assert imported.shots[2].audition.input_key == stale
    assert json.loads(stale)[1] != imported.shots[2].draft.audio_id


@pytest.mark.parametrize("seed", [2**53 - 1, 2**53 + 1, 2**63 - 1])
def test_browser_seed_transport_and_project_packages_are_lossless(tmp_path, seed):
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", inference_enabled=False),
        base_url="http://localhost",
    )
    project = client.post("/api/projects", json={"title": "Exact seed"}).json()
    project["shots"][0]["draft"]["seed"] = str(seed)
    saved = client.put(f"/api/projects/{project['id']}", json=project)
    assert saved.status_code == 200, saved.text
    browser_seed = seed if seed <= 2**53 - 1 else str(seed)
    assert saved.json()["shots"][0]["draft"]["seed"] == browser_seed
    assert (
        ProjectStore(tmp_path / "projects").load(project["id"]).shots[0].draft.seed
        == seed
    )
    receipt = client.post(
        f"/api/projects/{project['id']}/packages",
        json={"request_id": "a" * 32, "revision": saved.json()["revision"]},
    ).json()
    archive = tmp_path / "packages" / receipt["id"] / "project.aipg.zip"
    with zipfile.ZipFile(archive) as package:
        assert (
            json.loads(package.read("project.json"))["project"]["shots"][0]["draft"][
                "seed"
            ]
            == seed
        )
    imported = client.post(
        "/api/project-imports/" + "b" * 32,
        content=archive.read_bytes(),
        headers={"content-type": "application/zip"},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["project"]["shots"][0]["draft"]["seed"] == browser_seed
