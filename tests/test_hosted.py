import json
from io import BytesIO

import pytest
from PIL import Image
from test_auth import google, post

from aipg_cinema import app
from aipg_cinema.auth import SESSION_COOKIE
from aipg_cinema.contracts import TakeRequest


def test_anonymous_requests_cannot_reach_any_workspace(login_api, tmp_path):
    _, calls, _, _, open_client = login_api
    client = open_client(hosted=True)
    assert client.get("/", follow_redirects=False).headers["location"] == "/signin"
    assert client.get("/signin").status_code == 200
    for path in (
        "/api/config",
        "/api/projects",
        "/api/jobs",
        "/session.js",
        "/api/looks/" + "a" * 32,
    ):
        response = client.get(path)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
    assert not list((tmp_path / "workspaces").iterdir())
    assert not calls


def test_projects_uploads_and_reopening_are_account_scoped(login_api, tmp_path):
    _, _, _, _, open_client = login_api
    first, second = open_client(hosted=True), open_client(hosted=True)
    a, b = google(first).json(), google(second, "proof-b").json()
    assert a["workspace_id"] != b["workspace_id"]
    created = post(
        first,
        "/api/projects",
        {"title": "Private project", "frame_format": "square"},
        a["csrf"],
    )
    assert created.status_code == 200
    project = created.json()
    assert (
        first.get(f"/api/projects/{project['id']}").json()["title"] == "Private project"
    )
    assert second.get("/api/projects").json() == []
    assert second.get(f"/api/projects/{project['id']}").status_code == 404
    assert (
        post(second, "/api/projects", {"title": "Not allowed"}, a["csrf"]).status_code
        == 401
    )

    image = BytesIO()
    Image.new("RGB", (256, 256), "green").save(image, format="PNG")
    uploaded = first.post(
        "/api/looks?frame_format=square",
        files={"file": ("reference.png", image.getvalue(), "image/png")},
        headers={"origin": "https://studio.example", "x-studio-csrf": a["csrf"]},
    )
    assert uploaded.status_code == 200
    path = uploaded.json()["url"]
    assert first.get(path).status_code == 200
    assert second.get(path).status_code == 404
    reopened = open_client(hosted=True)
    reopened.cookies.update(first.cookies)
    assert reopened.get(f"/api/projects/{project['id']}").json() == project
    assert reopened.get(path).content == first.get(path).content
    assert (tmp_path / "workspaces" / a["workspace_id"]).stat().st_mode & 0o777 == 0o700


def test_creation_receipts_are_account_scoped_and_never_create_on_read(login_api):
    _, _, _, _, open_client = login_api
    first, second = open_client(hosted=True), open_client(hosted=True)
    a, b = google(first).json(), google(second, "proof-b").json()
    path = "/api/project-creations/" + "c" * 32
    body = {"title": "Private creation", "frame_format": "square", "structure": "blank"}
    receipt = post(first, path, body, a["csrf"])
    assert receipt.status_code == 200
    assert first.get(path).json() == receipt.json()
    assert second.get(path).status_code == 404
    assert second.get("/api/projects").json() == []
    assert post(second, path, body, a["csrf"]).status_code == 401
    other = post(second, path, {**body, "title": "Another account"}, b["csrf"])
    assert other.status_code == 200
    assert second.get(path).json()["project"]["title"] == "Another account"
    assert first.get(path).json() == receipt.json()


def test_metadata_outputs_and_downloads_cannot_cross_accounts(login_api, tmp_path):
    _, _, _, _, open_client = login_api
    first, second = open_client(hosted=True), open_client(hosted=True)
    identity = google(first).json()
    google(second, "proof-b")
    assert first.get("/api/config").status_code == 200
    root = tmp_path / "workspaces" / identity["workspace_id"]
    job_id = "b" * 32
    job = root / "jobs" / job_id
    (job / "render").mkdir(parents=True)
    (job / "request.json").write_text(
        TakeRequest(
            request_id=job_id, mode="text", prompt="Private fixture"
        ).model_dump_json()
    )
    (job / "render" / "reshoot.mp4").write_bytes(
        b"private output fixture, not a render"
    )
    assert first.get(f"/api/jobs/{job_id}").json()["prompt"] == "Private fixture"
    assert first.get(f"/api/jobs/{job_id}/output").content.startswith(b"private output")
    for path in (
        f"/api/jobs/{job_id}",
        f"/api/jobs/{job_id}/output",
        f"/api/jobs/{job_id}/settings",
        f"/api/jobs/{job_id}/workflow",
    ):
        assert second.get(path).status_code == 404
    assert second.get("/api/jobs").json() == []
    assert second.get("/api/config").json()["renders_used"] == 0


def test_billing_gate_blocks_every_inference_path_before_writing_or_probing(
    login_api, tmp_path, monkeypatch
):
    _, _, _, _, open_client = login_api
    client = open_client(hosted=True)
    state = google(client).json()

    def forbidden(*args, **kwargs):
        raise AssertionError("Staging must not probe providers or execute inference.")

    monkeypatch.setattr(app, "sdk_client", forbidden)
    monkeypatch.setattr(app.subprocess, "Popen", forbidden)
    config = client.get("/api/config").json()
    assert config["inference_enabled"] is False
    assert config["connected"] is config["look_connected"] is False
    for path in (
        "/api/jobs",
        "/api/look-jobs",
        "/api/jobs/" + "a" * 32 + "/resume",
        "/api/look-jobs/" + "a" * 32 + "/resume",
        "/api/projects/" + "a" * 32 + "/shots/" + "b" * 32 + "/generate",
    ):
        assert post(client, path, {}, state["csrf"]).status_code == 503
    root = tmp_path / "workspaces" / state["workspace_id"]
    assert not list((root / "jobs").iterdir())
    assert not list((root / "looks").iterdir())


def test_bootstrap_only_contains_verified_safe_session_and_logout_revokes_all_routes(
    login_api,
):
    _, _, _, _, open_client = login_api
    client = open_client(hosted=True)
    state = google(client).json()
    bootstrap = client.get("/session.js")
    assert bootstrap.status_code == 200
    assert bootstrap.headers["content-type"].startswith("text/javascript")
    data = json.loads(
        bootstrap.text.removeprefix("window.studioSession = ").removesuffix(";")
    )
    assert data == {**state, "mode": "hosted"}
    assert "delegated-secret" not in bootstrap.text
    assert client.cookies.get(SESSION_COOKIE) not in bootstrap.text
    old_handle = client.cookies.get(SESSION_COOKIE)
    assert post(client, "/auth/logout", {}, state["csrf"]).status_code == 200
    client.cookies.set(SESSION_COOKIE, old_handle)
    assert client.get("/api/projects").status_code == 401
    assert client.get("/session.js").status_code == 401


def test_local_app_keeps_loopback_protection_and_cannot_enable_unbilled_hosted_renders(
    tmp_path,
):
    with pytest.raises(ValueError, match="billing"):
        app.create_app(tmp_path, account_host="studio.example")


def test_atomic_page_bootstrap_cannot_inject_html_or_require_a_second_request(
    login_api,
):
    _, _, _, _, open_client = login_api
    client = open_client(hosted=True)
    identity = google(client).json()
    page = client.get("/")
    assert page.status_code == 200
    assert identity["workspace_id"] in page.text
    assert '<script src="/session.js"' not in page.text
    assert "delegated-secret" not in page.text
    malicious = '</script><img src=x onerror="alert(1)">'
    response = app.index_response({"untrusted": malicious})
    assert malicious.encode() not in response.body
    assert b"\\u003c/script>" in response.body


def test_source_audio_caption_and_export_assets_keep_the_same_account_boundary(
    login_api, tmp_path
):
    _, _, _, _, open_client = login_api
    first, second = open_client(hosted=True), open_client(hosted=True)
    identity = google(first).json()
    google(second, "proof-b")
    project = post(
        first, "/api/projects", {"title": "Private fixture"}, identity["csrf"]
    ).json()
    root = tmp_path / "workspaces" / identity["workspace_id"]
    media_id, export_id, caption_id = "c" * 32, "d" * 32, "e" * 64
    source = root / "sources" / media_id
    (source / "preview").mkdir(parents=True)
    (source / "source.mp4").write_bytes(b"private original fixture")
    (source / "preview" / "source.mp4").write_bytes(b"private preview fixture")
    (source / "source.json").write_text(
        json.dumps({"duration": 5, "has_audio": True, "name": "Private source"})
    )
    assert first.get(f"/api/sources/{media_id}").content == b"private preview fixture"
    audio = root / "audio" / media_id
    audio.mkdir()
    (audio / "original.wav").write_bytes(b"private audio fixture")
    (audio / "audio.json").write_text(
        json.dumps(
            {
                "audio_id": media_id,
                "suffix": ".wav",
                "name": "Private audio",
                "duration": 5,
            }
        )
    )
    assert first.get(f"/api/audio/{media_id}/info").json()["name"] == "Private audio"
    (root / "caption-previews" / f"{caption_id}.png").write_bytes(
        b"private caption fixture"
    )
    assert (
        first.get(f"/api/caption-previews/{caption_id}").content
        == b"private caption fixture"
    )
    output = root / "exports" / export_id
    output.mkdir()
    (output / "request.json").write_text(json.dumps({"project_id": project["id"]}))
    (output / "project.json").write_text(json.dumps(project))
    (output / "short.mp4").write_bytes(b"private short fixture")
    assert (
        first.get(f"/api/exports/{export_id}/output").content
        == b"private short fixture"
    )
    headers = {
        "X-Account-ID": identity["account_id"],
        "X-Workspace-ID": identity["workspace_id"],
    }
    for path in (
        f"/api/sources/{media_id}",
        f"/api/sources/{media_id}/info",
        f"/api/sources/{media_id}/frame",
        f"/api/audio/{media_id}",
        f"/api/audio/{media_id}/info",
        f"/api/audio/{media_id}/soundtrack",
        f"/api/caption-previews/{caption_id}",
        f"/api/exports/{export_id}",
        f"/api/exports/{export_id}/output",
        f"/api/exports/{export_id}/project",
    ):
        assert (
            second.get(
                path, headers=headers, params={"workspace_id": identity["workspace_id"]}
            ).status_code
            == 404
        )
