import json
import shutil
import subprocess
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aipg_cinema import app
from aipg_cinema.reshoot import probe


@pytest.fixture
def local(tmp_path, monkeypatch):
    processes = []
    monkeypatch.setenv("COMFY_BASE_URL", "http://127.0.0.1:18291")
    monkeypatch.setenv("COMFY_UPSTREAM_URL", "http://127.0.0.1:18189")

    def get(url, **kwargs):
        node = url.rsplit("/", 1)[-1]
        fields = {
            "LTXVAddGuide": {
                "positive",
                "negative",
                "vae",
                "latent",
                "image",
                "frame_idx",
                "strength",
            },
            "LTXVCropGuides": {"positive", "negative", "latent"},
        }
        data = (
            {node: {"input": {"required": dict.fromkeys(fields[node])}}}
            if node in fields
            else {"devices": []}
        )
        return SimpleNamespace(status_code=200, json=lambda: data)

    monkeypatch.setattr(app.httpx, "get", get)

    class Process:
        returncode = None

        def __init__(self, args, **kwargs):
            self.args = args
            processes.append(self)

        def poll(self):
            return self.returncode

    monkeypatch.setattr(app.subprocess, "Popen", Process)
    monkeypatch.setattr(
        app,
        "probe",
        lambda p: {"streams": [{"codec_type": "video"}], "format": {"duration": "5.2"}},
    )
    monkeypatch.setattr(
        app,
        "prepare_source",
        lambda source, destination, **options: shutil.copyfile(
            source, destination / "source.mp4"
        ),
    )
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", 1), base_url="http://localhost"
    )
    return client, tmp_path, processes


def upload(client):
    response = client.post(
        "/api/sources", files={"file": ("source.mp4", b"test video fixture bytes")}
    )
    assert response.status_code == 200
    return response.json()["source_id"]


@pytest.mark.parametrize(
    "frame_format,size", [("portrait", (1152, 2048)), ("square", (1280, 1280))]
)
def test_window_reaches_renderer_and_export_metadata(local, frame_format, size):
    client, root, processes = local
    source = upload(client)
    body = {**take(source), "frame_format": frame_format, "source_start": 0.1}
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200
    arguments = processes[0].args
    assert arguments[arguments.index("--format") + 1] == frame_format
    assert arguments[arguments.index("--source-start") + 1] == "0.1"
    assert (
        f"frame_format={frame_format}&source_start=0.1" in response.json()["source_url"]
    )
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    assert client.post("/api/jobs", json={**body, "source_start": 0}).status_code == 409
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert (settings["width"], settings["height"]) == size
    assert settings["source_start"] == 0.1
    assert (
        root / "sources" / source / "source.mp4"
    ).read_bytes() == b"test video fixture bytes"


def test_preview_cache_does_not_dispatch_and_invalid_queries_are_rejected(
    local, monkeypatch
):
    client, root, processes = local
    source = upload(client)
    calls = []

    def encode(original, folder, **options):
        calls.append(options)
        (folder / "source.mp4").write_bytes(b"portrait preview")

    monkeypatch.setattr(app, "prepare_source", encode)
    path = f"/api/sources/{source}?frame_format=portrait&source_start=0.1"
    assert client.get(path).content == b"portrait preview"
    assert client.get(path).content == b"portrait preview"
    assert calls == [{"frame_format": "portrait", "source_start": 0.1, "seconds": 5}]
    # A ten-second window is prepared separately; five-second keys are unchanged.
    assert client.get(path + "&seconds=10").content == b"portrait preview"
    assert calls[-1] == {"frame_format": "portrait", "source_start": 0.1, "seconds": 10}
    assert client.get(path + "&seconds=7").status_code == 422
    assert not processes
    assert not list((root / "sources" / source / "windows").glob(".preparing-*"))
    assert client.get(f"/api/sources/{source}?frame_format=bad").status_code == 422
    assert client.get(f"/api/sources/{source}?source_start=-1").status_code == 422
    assert client.get(f"/api/sources/{source}/info").json()["duration"] == 5.2


def test_look_cannot_be_reused_for_another_window_or_framing(moss):
    client, root, processes = moss
    source = upload(client)
    body = {**look_request(source), "frame_format": "portrait", "source_start": 0.1}
    assert client.post("/api/look-jobs", json=body).status_code == 200
    generated = root / "looks" / body["request_id"] / "render"
    generated.mkdir()
    Image.new("RGB", (180, 320), "blue").save(generated / "look.png")
    video = {**take(source), "request_id": "b" * 32, "look_id": body["request_id"]}
    assert client.post("/api/jobs", json=video).status_code == 400
    assert (
        client.post("/api/jobs", json={**video, "frame_format": "portrait"}).status_code
        == 400
    )
    assert len(processes) == 1
    assert (
        client.post(
            "/api/jobs", json={**video, "frame_format": "portrait", "source_start": 0.1}
        ).status_code
        == 200
    )
    assert len(processes) == 2


def take(source_id):
    return {
        "request_id": "a" * 32,
        "source_id": source_id,
        "prompt": "A blue toy car in a desert",
        "seed": 42,
    }


def upload_look(client):
    content = BytesIO()
    Image.new("RGBA", (96, 56), (220, 90, 10, 255)).save(content, format="PNG")
    response = client.post(
        "/api/looks", files={"file": ("look.png", content.getvalue(), "image/png")}
    )
    assert response.status_code == 200
    return response.json()["look_id"]


@pytest.mark.parametrize("mode", ["text", "image"])
def test_new_generation_modes_are_idempotent_and_do_not_require_a_video(local, mode):
    client, root, processes = local
    body = {
        "request_id": "a" * 32,
        "mode": mode,
        "prompt": "A paper sailboat",
        "seed": 42,
    }
    if mode == "image":
        body["look_id"] = upload_look(client)
    first = client.post("/api/jobs", json=body)
    assert first.status_code == 200
    assert first.json()["source_url"] is None
    assert first.json()["source_image_url"] == (
        f"/api/looks/{body['look_id']}" if mode == "image" else None
    )
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    assert "generate" in processes[0].args and "reshoot" not in processes[0].args
    assert processes[0].args[processes[0].args.index("--mode") + 1] == mode
    assert "None" not in processes[0].args
    metadata = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert metadata["mode"] == mode and metadata["source"] is None
    assert not metadata["audio_conditioned"]
    assert not list((root / "sources").iterdir())
    assert client.post("/api/jobs", json={**body, "seed": 43}).status_code == 409


@pytest.mark.parametrize(
    "fields",
    [
        {"mode": "image"},
        {"mode": "audio"},
        {"mode": "video"},
        {"mode": "text", "source_id": "b" * 32},
        {"mode": "text", "audio_id": "c" * 32},
        {"mode": "text", "source_start": 2},
        {"mode": "text", "reference_image": "unsupported"},
    ],
)
def test_new_modes_never_silently_drop_missing_or_unsupported_inputs(local, fields):
    client, root, processes = local
    body = {"request_id": "a" * 32, "prompt": "A paper sailboat", **fields}
    assert client.post("/api/jobs", json=body).status_code == 422
    assert not list((root / "jobs").iterdir()) and not processes


def test_audio_upload_mode_range_and_replay_are_separate_from_video(local, monkeypatch):
    client, root, processes = local
    monkeypatch.setattr(
        app,
        "audio_info",
        lambda path: {
            "format": {"duration": "12"},
            "streams": [{"codec_type": "audio", "duration": "12"}],
        },
    )

    def prepare(path, folder, start):
        assert start == 6
        destination = folder / "source.wav"
        destination.write_bytes(b"synthetic normalized WAV")
        return destination

    monkeypatch.setattr(app, "prepare_audio", prepare)
    uploaded = client.post(
        "/api/audio", files={"file": ("music.wav", b"synthetic source WAV")}
    )
    assert uploaded.status_code == 200
    audio = uploaded.json()["audio_id"]
    assert uploaded.json()["duration"] == 12
    assert client.get(f"/api/audio/{audio}/info").json()["name"] == "music.wav"
    assert (
        client.get(f"/api/audio/{audio}?source_start=6").content
        == b"synthetic normalized WAV"
    )
    body = {
        "request_id": "a" * 32,
        "mode": "audio",
        "audio_id": audio,
        "source_start": 6,
        "frame_format": "square",
        "prompt": "A toy drummer",
    }
    assert client.post("/api/jobs", json=body).status_code == 200
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    args = processes[0].args
    assert args[args.index("--audio") + 1] == str(
        root / "audio" / audio / "original.wav"
    )
    assert args[args.index("--source-start") + 1] == "6.0"
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["audio_conditioned"] and settings["source"] == "source.wav"
    assert (settings["width"], settings["height"]) == (1280, 1280)
    assert (
        client.post(
            "/api/audio", files={"file": ("remote.m3u8", b"#EXTM3U")}
        ).status_code
        == 400
    )
    assert len(processes) == 1


@pytest.fixture
def moss(local, monkeypatch):
    monkeypatch.setenv("COMFY_LOOK_BASE_URL", "http://127.0.0.1:18389")
    monkeypatch.setenv("COMFY_LOOK_UPSTREAM_URL", "http://127.0.0.1:18388")
    models = {
        "UNETLoader": ("unet_name", "moss_image_sft_bf16.safetensors"),
        "CLIPLoader": ("clip_name", "qwen3.5_9b_int8_convrot.safetensors"),
        "VAELoader": ("vae_name", "flux2-vae.safetensors"),
    }

    def get(url, **kwargs):
        node = url.rsplit("/", 1)[-1]
        data = {"devices": []}
        if node in models:
            field, filename = models[node]
            data = {node: {"input": {"required": {field: [[filename]]}}}}
        elif node == "SkipLayerGuidanceDiTSimple":
            data = {
                node: {
                    "input": {
                        "required": {
                            field: []
                            for field in (
                                "model",
                                "single_layers",
                                "double_layers",
                                "start_percent",
                                "end_percent",
                            )
                        }
                    }
                }
            }
        elif node in ("LTXVAddGuide", "LTXVCropGuides"):
            fields = {"positive", "negative", "latent"}
            if node == "LTXVAddGuide":
                fields |= {"vae", "image", "frame_idx", "strength"}
            data = {node: {"input": {"required": dict.fromkeys(fields)}}}
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))

    monkeypatch.setattr(app.httpx, "get", get)
    return local


def look_request(source_id):
    return {**take(source_id), "denoise": 0.65}


def test_moss_look_is_idempotent_and_never_submits_a_video(moss):
    client, root, processes = moss
    body = look_request(upload(client))
    assert client.post("/api/look-jobs", json=body).status_code == 200
    assert client.post("/api/look-jobs", json=body).status_code == 200
    assert len(processes) == 1
    assert "look" in processes[0].args
    assert "reshoot" not in processes[0].args
    assert not list((root / "jobs").iterdir())
    assert client.post("/api/look-jobs", json={**body, "seed": 99}).status_code == 409
    assert len(processes) == 1


def test_unavailable_moss_or_invalid_strength_never_creates_a_job(
    local, moss, monkeypatch
):
    client, root, processes = local
    body = look_request(upload(client))
    assert (
        client.post("/api/look-jobs", json={**body, "denoise": 0.85}).status_code == 422
    )
    monkeypatch.setattr(
        app.httpx,
        "get",
        lambda url, **kw: httpx.Response(
            200, json={"devices": []}, request=httpx.Request("GET", url)
        ),
    )
    assert client.post("/api/look-jobs", json=body).status_code == 503
    assert not list((root / "looks").iterdir())
    assert not processes


def test_unknown_moss_submission_blocks_another_look(moss):
    client, _, processes = moss
    body = look_request(upload(client))
    client.post("/api/look-jobs", json=body)
    processes[0].returncode = 1
    assert (
        client.get(f"/api/look-jobs/{body['request_id']}").json()["status"]
        == "needs_review"
    )
    assert client.post(f"/api/look-jobs/{body['request_id']}/resume").status_code == 409
    assert (
        client.post("/api/look-jobs", json={**body, "request_id": "b" * 32}).status_code
        == 409
    )
    assert len(processes) == 1


def test_missing_native_moss_guidance_is_rejected_before_submission(moss, monkeypatch):
    client, root, processes = moss
    original = app.httpx.get

    def get(url, **kwargs):
        if url.endswith("/SkipLayerGuidanceDiTSimple"):
            return httpx.Response(200, json={}, request=httpx.Request("GET", url))
        return original(url, **kwargs)

    monkeypatch.setattr(app.httpx, "get", get)
    assert (
        client.post("/api/look-jobs", json=look_request(upload(client))).status_code
        == 503
    )
    assert not list((root / "looks").iterdir())
    assert not processes


def test_saved_moss_recovery_pins_look_credentials_and_reuses_job(moss, monkeypatch):
    client, root, processes = moss
    body = look_request(upload(client))
    client.post("/api/look-jobs", json=body)
    processes[0].returncode = 1
    rendered = root / "looks" / body["request_id"] / "render"
    rendered.mkdir()
    (rendered / "job.json").write_text(
        json.dumps(
            {
                "job_id": "existing-look",
                "look_render": True,
                "backend": "self-hosted",
                "base_url": "http://127.0.0.1:18389",
            }
        )
    )

    @contextmanager
    def sdk(backend, endpoint, *, credential_scope, timeout):
        assert (backend, endpoint, credential_scope) == (
            "self-hosted",
            "http://127.0.0.1:18389",
            "look",
        )
        assert timeout == 5.0
        yield SimpleNamespace(
            jobs=SimpleNamespace(get=lambda _: SimpleNamespace(status="succeeded"))
        )

    monkeypatch.setattr(app, "sdk_client", sdk)
    restarted = TestClient(app.create_app(root), base_url="http://localhost")
    assert restarted.get("/api/look-jobs").json()[0]["status"] == "needs_recovery"
    assert (
        restarted.post(f"/api/look-jobs/{body['request_id']}/resume").status_code == 200
    )
    assert processes[1].args[-2:] == ["resume", str(rendered)]
    assert len(processes) == 2


@pytest.mark.parametrize("skip_layers", [[], [22]])
def test_generated_look_exports_reproducible_settings_without_credentials(
    moss, skip_layers
):
    client, root, processes = moss
    body = look_request(upload(client))
    client.post("/api/look-jobs", json=body)
    processes[0].returncode = 0
    rendered = root / "looks" / body["request_id"] / "render"
    rendered.mkdir()
    image = BytesIO()
    Image.new("RGB", (96, 56), "coral").save(image, format="PNG")
    for name in ("look.png", "source.png"):
        (rendered / name).write_bytes(image.getvalue())
    (rendered / "workflow.json").write_text('{"fixture": "portable graph"}')
    if skip_layers:
        (rendered / "job.json").write_text(
            json.dumps({"negative_skip_layers": skip_layers})
        )
    assert client.get("/api/look-jobs").json()[0]["status"] == "succeeded"
    video = {**take(body["source_id"]), "look_id": body["request_id"]}
    response = client.post("/api/jobs", json=video)
    assert response.json()["generated_look"] is True
    assert len(processes) == 2
    settings = client.get(f"/api/jobs/{video['request_id']}/settings").json()
    assert settings["opening_look"] == {
        "model": "MOSS Image SFT BF16",
        "prompt": body["prompt"],
        "seed": 42,
        "denoise": 0.65,
        "negative_skip_layers": skip_layers,
        "source_frame_index": 0,
        "source": "source.png",
        "workflow": "look-workflow.json",
    }
    assert "base_url" not in json.dumps(settings)
    workflow = client.get(f"/api/jobs/{video['request_id']}/look-workflow")
    assert workflow.json() == {"fixture": "portable graph"}
    assert 'filename="look-workflow.json"' in workflow.headers["content-disposition"]
    assert (
        client.get(f"/api/jobs/{video['request_id']}/look-source").content
        == image.getvalue()
    )


def test_moss_cap_is_separate_from_video_cap(moss):
    client, root, _ = moss
    body = look_request(upload(client))
    folder = root / "looks" / body["request_id"]
    folder.mkdir()
    (folder / "request.json").write_text(json.dumps(body))
    (folder / "render").mkdir()
    (folder / "render" / "look.png").write_bytes(b"synthetic fixture")
    limited = TestClient(
        app.create_app(root, max_renders=1, max_looks=1), base_url="http://localhost"
    )
    assert limited.get("/api/config").json()["renders_used"] == 0
    assert (
        limited.post(
            "/api/look-jobs", json={**body, "request_id": "b" * 32}
        ).status_code
        == 429
    )
    assert limited.post("/api/look-jobs", json=body).status_code == 200


def test_look_health_sends_only_its_own_token_to_its_loopback_proxy(moss, monkeypatch):
    client, _, _ = moss
    monkeypatch.setenv("COMFY_API_KEY", "test-cloud-secret")
    monkeypatch.setenv("COMFY_LOCAL_TOKEN", "test-video-secret")
    monkeypatch.setenv("COMFY_LOOK_LOCAL_TOKEN", "test-look-secret")
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("headers", {})))
        return httpx.Response(200, json={"devices": []})

    monkeypatch.setattr(app.httpx, "get", get)
    assert client.get("/api/config").json()["look_connected"] is True
    look_calls = [(url, headers) for url, headers in calls if ":1838" in url]
    assert look_calls == [
        (
            "http://127.0.0.1:18389/api/v2/health",
            {"Authorization": "Bearer test-look-secret"},
        ),
        ("http://127.0.0.1:18388/system_stats", {}),
    ]


def test_ui_config_and_cross_origin_rejection(local):
    client, _, processes = local
    assert client.get("/").status_code == 200
    config = client.get("/api/config").json()
    assert config["backend"] == "self-hosted"
    assert "key" not in str(config).lower()
    assert (
        client.post(
            "/api/demo/source", headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert processes == []


def test_duplicate_submission_starts_only_one_render(local):
    client, _, processes = local
    body = take(upload(client))
    assert client.post("/api/jobs", json=body).status_code == 200
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    assert "ltx25" in processes[0].args
    assert "self-hosted" in processes[0].args
    assert client.get("/api/jobs").json()[0]["id"] == body["request_id"]
    assert (
        client.post("/api/jobs", json={**body, "prompt": "changed"}).status_code == 409
    )
    assert len(processes) == 1


def test_old_requests_without_a_look_field_remain_idempotent(local):
    client, root, processes = local
    body = take(upload(client))
    assert client.post("/api/jobs", json=body).status_code == 200
    request = root / "jobs" / body["request_id"] / "request.json"
    old = json.loads(request.read_text())
    old.pop("look_id")
    old.pop("closing_id")
    old.pop("art_direction")
    old.pop("motion_prompt")
    request.write_text(json.dumps(old))
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1


def test_separate_prompts_survive_restart_export_and_idempotency(local):
    client, root, processes = local
    body = {
        **take(upload(client)),
        "prompt": "Follow the source movement with the selected look.",
        "art_direction": "Warm amber light and copper surfaces.",
        "motion_prompt": "Follow the source movement with the selected look.",
    }
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200
    args = processes[0].args
    assert args[args.index("--prompt") + 1] == body["prompt"]
    restarted = TestClient(
        app.create_app(root, "self-hosted"), base_url="http://localhost"
    )
    saved = restarted.get("/api/jobs").json()[0]
    settings = restarted.get(f"/api/jobs/{body['request_id']}/settings").json()
    for key in ("prompt", "art_direction", "motion_prompt"):
        assert saved[key] == settings[key] == body[key]
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    assert (
        client.post(
            "/api/jobs", json={**body, "art_direction": "Another saved look direction"}
        ).status_code
        == 409
    )


def test_prompt_metadata_is_bounded_before_creating_a_take(local):
    client, root, processes = local
    body = {**take(upload(client)), "art_direction": "a" * 4001}
    assert client.post("/api/jobs", json=body).status_code == 422
    assert not processes
    assert not list((root / "jobs").iterdir())


def test_closing_upload_requires_opening_and_is_snapshotted(local):
    client, root, processes = local
    source_id = upload(client)
    closing_id = upload_look(client)
    body = {**take(source_id), "closing_id": closing_id}
    assert client.post("/api/jobs", json=body).status_code == 400
    assert not processes
    assert not list((root / "jobs").iterdir())
    opening_id = upload_look(client)
    body["look_id"] = opening_id
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200
    assert response.json()["closing_url"] == f"/api/looks/{closing_id}"
    snapshot = root / "jobs" / body["request_id"] / "closing.png"
    assert snapshot.read_bytes() == client.get(f"/api/looks/{closing_id}").content
    assert processes[0].args[-2:] == ["--closing-frame", str(snapshot)]
    assert client.post("/api/jobs", json=body).status_code == 200
    assert (
        client.post("/api/jobs", json={**body, "closing_id": None}).status_code == 409
    )
    assert len(processes) == 1
    render = snapshot.parent / "render"
    render.mkdir()
    shutil.copyfile(snapshot, render / "closing.png")
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["closing_frame"] == "closing.png"
    assert settings["closing_frame_index"] == 120
    assert settings["closing_strength"] == 0.7
    downloaded = client.get(f"/api/jobs/{body['request_id']}/closing")
    assert downloaded.content == snapshot.read_bytes()
    assert 'filename="closing.png"' in downloaded.headers["content-disposition"]


def complete_look(root, processes, body):
    processes[-1].returncode = 0
    render = root / "looks" / body["request_id"] / "render"
    render.mkdir()
    image = BytesIO()
    Image.new("RGB", (96, 56), "coral").save(image, format="PNG")
    for name in ("look.png", "source.png"):
        (render / name).write_bytes(image.getvalue())
    (render / "workflow.json").write_text('{"fixture": "portable graph"}')
    (render / "job.json").write_text(
        json.dumps(
            {
                "source_frame_index": body.get("frame_index", 0),
                "negative_skip_layers": [22],
            }
        )
    )


def test_generated_closing_roles_exports_and_replay_are_distinct(moss):
    client, root, processes = moss
    source_id = upload(client)
    opening = look_request(source_id)
    assert client.post("/api/look-jobs", json=opening).status_code == 200
    complete_look(root, processes, opening)
    closing = {**opening, "request_id": "b" * 32, "frame_index": 120}
    assert client.post("/api/look-jobs", json=closing).status_code == 200
    assert processes[-1].args[processes[-1].args.index("--frame-index") + 1] == "120"
    assert client.post("/api/look-jobs", json=closing).status_code == 200
    assert (
        client.post("/api/look-jobs", json={**closing, "frame_index": 0}).status_code
        == 409
    )
    complete_look(root, processes, closing)
    assert [job["frame_index"] for job in client.get("/api/look-jobs").json()] == [
        0,
        120,
    ]
    body = {
        **take(source_id),
        "look_id": opening["request_id"],
        "closing_id": closing["request_id"],
    }
    assert client.post("/api/jobs", json=body).status_code == 200
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["opening_look"]["source_frame_index"] == 0
    assert settings["closing_look"]["source_frame_index"] == 120
    assert settings["closing_look"]["workflow"] == "closing-workflow.json"
    assert settings["closing_look"]["source"] == "closing-source.png"
    assert len(processes) == 3
    for kind, filename in (
        ("closing-workflow", "closing-workflow.json"),
        ("closing-source", "closing-source.png"),
    ):
        response = client.get(f"/api/jobs/{body['request_id']}/{kind}")
        assert response.status_code == 200
        assert f'filename="{filename}"' in response.headers["content-disposition"]
    restarted = TestClient(
        app.create_app(root, "self-hosted"), base_url="http://localhost"
    )
    assert restarted.get("/api/jobs").json()[0]["closing_id"] == closing["request_id"]


def test_generated_references_cannot_cross_source_or_frame(moss):
    client, root, processes = moss
    original = upload(client)
    other = upload(client)
    body = {**look_request(original), "frame_index": 120}
    assert client.post("/api/look-jobs", json=body).status_code == 200
    complete_look(root, processes, body)
    assert (
        client.post(
            "/api/jobs", json={**take(original), "look_id": body["request_id"]}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/jobs",
            json={
                **take(other),
                "look_id": upload_look(client),
                "closing_id": body["request_id"],
            },
        ).status_code
        == 400
    )
    assert not list((root / "jobs").iterdir())
    assert len(processes) == 1


def test_missing_closing_nodes_do_not_consume_a_render(local, monkeypatch):
    client, root, processes = local
    source_id = upload(client)
    body = {
        **take(source_id),
        "look_id": upload_look(client),
        "closing_id": upload_look(client),
    }
    original = app.httpx.get

    def get(url, **kwargs):
        if url.endswith("/object_info/LTXVAddGuide"):
            return SimpleNamespace(status_code=200, json=dict)
        return original(url, **kwargs)

    monkeypatch.setattr(app.httpx, "get", get)
    assert client.get("/api/config").json()["closing_supported"] is False
    assert client.post("/api/jobs", json=body).status_code == 503
    assert not list((root / "jobs").iterdir())
    assert not processes


@pytest.fixture
def cloud(local, monkeypatch):
    _, root, processes = local
    monkeypatch.setenv("COMFY_BASE_URL", "https://cloud.comfy.org")
    monkeypatch.setenv("COMFY_API_KEY", "test-cloud-credential")
    monkeypatch.setenv("COMFY_LOOK_LOCAL_TOKEN", "test-look-only-credential")
    calls = []
    responses = [httpx.Response(200, json={"status": "active"})]
    original = app.httpx.get

    def get(url, **kwargs):
        if url == "https://cloud.comfy.org/api/user":
            calls.append((url, kwargs))
            response = responses.pop(0) if len(responses) > 1 else responses[0]
            if isinstance(response, Exception):
                raise response
            return response
        return original(url, **kwargs)

    monkeypatch.setattr(app.httpx, "get", get)
    client = TestClient(app.create_app(root, "cloud"), base_url="http://localhost")
    return client, root, processes, calls, responses


def test_cloud_exposes_the_qualified_closing_path_without_using_look_credentials(cloud):
    client, _root, processes, calls, _responses = cloud
    source_id = upload(client)
    body = {
        **take(source_id),
        "look_id": upload_look(client),
        "closing_id": upload_look(client),
    }
    assert client.get("/api/config").json()["closing_supported"] is True
    assert client.post("/api/jobs", json=body).status_code == 200
    assert processes[0].args[processes[0].args.index("--backend") + 1] == "cloud"
    assert "--closing-frame" in processes[0].args
    assert len(calls) == 2
    assert all(call[1]["timeout"] == 5 for call in calls)
    assert all(
        call[1]["headers"] == {"X-API-Key": "test-cloud-credential"} for call in calls
    )


@pytest.mark.parametrize(
    ("status", "payload"),
    [(401, {}), (503, {}), (200, []), (200, {"status": "waitlisted"})],
)
def test_cloud_rejection_never_creates_a_take(cloud, status, payload):
    client, root, processes, _calls, responses = cloud
    responses[:] = [httpx.Response(status, json=payload)]
    assert client.get("/api/config").json()["connected"] is False
    response = client.post("/api/jobs", json=take(upload(client)))
    assert response.status_code == 503
    assert "COMFY_API_KEY" in response.json()["detail"]
    assert not list((root / "jobs").iterdir())
    assert not processes


def test_cloud_submission_rechecks_a_cached_healthy_connection(cloud):
    client, root, processes, calls, responses = cloud
    responses.append(httpx.Response(401, json={}))
    assert client.get("/api/config").json()["connected"] is True
    assert client.get("/api/config").json()["connected"] is True
    assert len(calls) == 1
    assert client.post("/api/jobs", json=take(upload(client))).status_code == 503
    assert len(calls) == 2
    assert not list((root / "jobs").iterdir())
    assert not processes


@pytest.mark.parametrize("misconfigured", ["missing-key", "wrong-host"])
def test_cloud_configuration_fails_before_sending_a_credential(
    cloud, monkeypatch, misconfigured
):
    client, root, processes, calls, _responses = cloud
    if misconfigured == "missing-key":
        monkeypatch.delenv("COMFY_API_KEY")
    else:
        monkeypatch.setenv("COMFY_BASE_URL", "https://outside.invalid")
    assert client.get("/api/config").json()["connected"] is False
    assert client.post("/api/jobs", json=take(upload(client))).status_code == 503
    assert not calls
    assert not list((root / "jobs").iterdir())
    assert not processes


def test_cloud_status_timeout_is_not_a_render_submission(cloud):
    client, root, processes, _calls, responses = cloud
    responses[:] = [httpx.ReadTimeout("status probe timed out")]
    assert client.get("/api/config").json()["connected"] is False
    assert client.post("/api/jobs", json=take(upload(client))).status_code == 503
    assert not list((root / "jobs").iterdir())
    assert not processes


def test_cloud_look_is_explicit_idempotent_and_has_no_denoise(cloud):
    _, root, processes, calls, _ = cloud
    client = TestClient(
        app.create_app(root, "cloud", look_engine="klein-cloud"),
        base_url="http://localhost",
    )
    config = client.get("/api/config").json()
    assert config["look_engine"] == "klein-cloud"
    assert config["look_model"] == "FLUX.2 Klein 4B FP8"
    assert config["look_connected"] is True
    body = {**look_request(upload(client)), "denoise": None}
    first = client.post("/api/look-jobs", json=body)
    assert first.status_code == 200
    assert first.json()["model"] == "FLUX.2 Klein 4B FP8"
    assert client.post("/api/look-jobs", json=body).status_code == 200
    assert len(processes) == 1
    command = processes[0].args
    assert command[command.index("--engine") + 1] == "klein-cloud"
    assert "--denoise" not in command
    assert not list((root / "jobs").iterdir())
    stored = json.loads(
        (root / "looks" / body["request_id"] / "request.json").read_text()
    )
    assert stored["engine"] == "klein-cloud"
    assert all(c[1]["headers"] == {"X-API-Key": "test-cloud-credential"} for c in calls)


def test_cloud_look_rechecks_access_before_creating_any_job(cloud):
    _, root, processes, calls, responses = cloud
    client = TestClient(
        app.create_app(root, "cloud", look_engine="klein-cloud"),
        base_url="http://localhost",
    )
    assert client.get("/api/config").json()["look_connected"] is True
    responses[:] = [httpx.Response(401, json={})]
    body = {**look_request(upload(client)), "denoise": None}
    assert client.post("/api/look-jobs", json=body).status_code == 503
    assert len(calls) == 3
    assert not list((root / "looks").iterdir())
    assert not processes


def test_klein_rejects_moss_knobs_and_moss_rejects_missing_knobs(cloud, moss):
    _, root, processes, _, _ = cloud
    client = TestClient(
        app.create_app(root, "cloud", look_engine="klein-cloud"),
        base_url="http://localhost",
    )
    assert (
        client.post("/api/look-jobs", json=look_request(upload(client))).status_code
        == 422
    )
    moss_client, _, _ = moss
    assert (
        moss_client.post(
            "/api/look-jobs",
            json={**look_request(upload(moss_client)), "denoise": None},
        ).status_code
        == 422
    )
    assert not list((root / "looks").iterdir())
    assert not processes


def test_saved_cloud_look_recovers_and_exports_its_original_model(cloud, monkeypatch):
    _, root, processes, _, _ = cloud
    client = TestClient(
        app.create_app(root, "cloud", look_engine="klein-cloud"),
        base_url="http://localhost",
    )
    body = {**look_request(upload(client)), "denoise": None}
    assert client.post("/api/look-jobs", json=body).status_code == 200
    processes[0].returncode = 1
    render = root / "looks" / body["request_id"] / "render"
    render.mkdir()
    state = {
        "job_id": "existing-cloud-look",
        "backend": "cloud",
        "base_url": "https://cloud.comfy.org",
        "model": "FLUX.2 Klein 4B FP8",
        "look_render": True,
    }
    (render / "job.json").write_text(json.dumps(state))
    scopes = []

    @contextmanager
    def sdk(backend, base_url, *, credential_scope, timeout):
        scopes.append((backend, base_url, credential_scope))
        yield SimpleNamespace(
            jobs=SimpleNamespace(get=lambda _: SimpleNamespace(status="succeeded"))
        )

    monkeypatch.setattr(app, "sdk_client", sdk)
    # Changing the next-look engine must not change recovery of an old job.
    changed = TestClient(app.create_app(root, "cloud"), base_url="http://localhost")
    response = changed.post(f"/api/look-jobs/{body['request_id']}/resume")
    assert response.status_code == 200
    assert response.json()["model"] == "FLUX.2 Klein 4B FP8"
    assert scopes == [("cloud", "https://cloud.comfy.org", "cloud-look")] * 2
    assert processes[-1].args[-2:] == ["resume", str(render)]
    assert "look" not in processes[-1].args
    assert changed.post("/api/look-jobs", json=body).status_code == 200
    assert len(processes) == 2
    assert not list((root / "jobs").iterdir())
    processes[-1].returncode = 0
    Image.new("RGB", (1536, 896), "coral").save(render / "look.png")
    (render / "workflow.json").write_text('{"fixture": true}')
    video_body = {**take(body["source_id"]), "look_id": body["request_id"]}
    video = changed.post("/api/jobs", json=video_body)
    assert video.status_code == 200
    settings = changed.get(f"/api/jobs/{video_body['request_id']}/settings").json()
    assert settings["model"] == "ltx25"
    assert settings["opening_look"]["model"] == "FLUX.2 Klein 4B FP8"
    assert settings["opening_look"]["denoise"] is None
    assert settings["opening_look"]["negative_skip_layers"] == []
    assert changed.get(
        f"/api/jobs/{video_body['request_id']}/look-workflow"
    ).json() == {"fixture": True}


def test_missing_cloud_key_reports_a_setup_error_without_starting_server(
    monkeypatch, capsys
):
    monkeypatch.setattr("sys.argv", ["openreshoot", "--backend", "cloud"])
    monkeypatch.delenv("COMFY_API_KEY", raising=False)
    monkeypatch.delenv("COMFY_BASE_URL", raising=False)
    started = []
    monkeypatch.setattr(app.uvicorn, "run", lambda *a, **k: started.append(True))
    with pytest.raises(SystemExit) as error:
        app.main()
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "COMFY_API_KEY" in message
    assert "Traceback" not in message
    assert not started


def test_legacy_opening_requests_replay_without_a_frame_field(moss):
    client, root, processes = moss
    body = look_request(upload(client))
    assert client.post("/api/look-jobs", json=body).status_code == 200
    path = root / "looks" / body["request_id"] / "request.json"
    previous = json.loads(path.read_text())
    previous.pop("frame_index")
    path.write_text(json.dumps(previous))
    response = client.post("/api/look-jobs", json=body)
    assert response.status_code == 200
    assert response.json()["frame_index"] == 0
    assert len(processes) == 1


def test_unknown_look_frame_does_not_create_a_job(moss):
    client, root, processes = moss
    body = {**look_request(upload(client)), "frame_index": 119}
    assert client.post("/api/look-jobs", json=body).status_code == 422
    assert not list((root / "looks").iterdir())
    assert not processes


def test_opening_look_upload_is_normalized_and_wired_to_the_render(local):
    client, root, processes = local
    look_id = upload_look(client)
    preview = client.get(f"/api/looks/{look_id}")
    assert preview.headers["content-type"] == "image/png"
    with Image.open(BytesIO(preview.content)) as image:
        assert image.size == (1536, 896)
        assert image.mode == "RGB"
    assert not (root / "looks" / look_id / "upload").exists()
    body = {**take(upload(client)), "look_id": look_id}
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200
    assert response.json()["look_url"] == f"/api/looks/{look_id}"
    snapshot = root / "jobs" / body["request_id"] / "look.png"
    assert snapshot.read_bytes() == preview.content
    args = processes[0].args
    assert args[args.index("--look-frame") + 1] == str(snapshot)
    assert client.post("/api/jobs", json=body).status_code == 200
    assert len(processes) == 1
    assert client.post("/api/jobs", json={**body, "look_id": None}).status_code == 409
    render = snapshot.parent / "render"
    render.mkdir()
    (render / "look.png").write_bytes(preview.content)
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["look_frame"] == "look.png"
    assert settings["motion_strength"] == 1.0
    assert settings["ai_generated"] is True
    assert "look_id" not in settings
    output = client.get(f"/api/jobs/{body['request_id']}/look")
    assert output.content == preview.content
    assert 'filename="look.png"' in output.headers["content-disposition"]


def test_unknown_look_is_rejected_before_creating_a_take(local):
    client, root, processes = local
    body = {**take(upload(client)), "look_id": "b" * 32}
    assert client.post("/api/jobs", json=body).status_code == 404
    assert not list((root / "jobs").iterdir())
    assert not processes
    assert client.get("/api/looks/not-a-look").status_code == 404


def test_invalid_and_oversized_look_uploads_are_cleaned_up(local):
    client, root, processes = local
    assert (
        client.post(
            "/api/looks", files={"file": ("fake.png", b"not an image")}
        ).status_code
        == 400
    )
    assert not list((root / "looks").iterdir())
    response = client.post(
        "/api/looks", files={"file": ("big.png", b"x" * (12 * 1024 * 1024 + 1))}
    )
    assert response.status_code == 413
    assert not list((root / "looks").iterdir())
    assert not processes


def test_opening_look_upload_uses_the_same_origin_guard(local):
    client, _, processes = local
    assert (
        client.post(
            "/api/looks",
            files={"file": ("fake.png", b"test")},
            headers={"Origin": "https://external.invalid"},
        ).status_code
        == 403
    )
    assert not processes


def test_cap_rejects_another_take_and_invalid_seed_does_not_spawn(local):
    client, _, processes = local
    body = take(upload(client))
    assert client.post("/api/jobs", json={**body, "seed": -1}).status_code == 422
    assert not processes
    assert client.post("/api/jobs", json=body).status_code == 200
    assert (
        client.post("/api/jobs", json={**body, "request_id": "b" * 32}).status_code
        == 429
    )
    assert len(processes) == 1


def test_restart_and_recovery_never_create_replacement(local, monkeypatch):
    client, root, processes = local
    body = take(upload(client))
    client.post("/api/jobs", json=body)
    processes[0].returncode = 1
    rendered = root / "jobs" / body["request_id"] / "render"
    rendered.mkdir()
    (rendered / "job.json").write_text(
        json.dumps(
            {
                "job_id": "existing-job",
                "backend": "self-hosted",
                "base_url": "http://127.0.0.1:18291",
            }
        )
    )

    @contextmanager
    def sdk(*args, **kwargs):
        yield SimpleNamespace(
            jobs=SimpleNamespace(get=lambda _: SimpleNamespace(status="succeeded"))
        )

    monkeypatch.setattr(app, "sdk_client", sdk)
    restarted = TestClient(
        app.create_app(root, "self-hosted", 1), base_url="http://localhost"
    )
    assert restarted.get("/api/jobs").json()[0]["status"] == "needs_recovery"
    assert len(processes) == 1
    response = restarted.post(f"/api/jobs/{body['request_id']}/resume")
    assert response.status_code == 200
    assert len(processes) == 2
    assert "resume" in processes[1].args
    assert "reshoot" not in processes[1].args
    assert len(list((root / "jobs").iterdir())) == 1


@pytest.mark.parametrize(
    ("provider_status", "active", "expected"),
    [
        ("queued", True, "queued"),
        ("running", True, "running"),
        ("succeeded", True, "exporting"),
        ("failed", True, "failed"),
        ("cancelled", True, "cancelled"),
        ("queued", False, "needs_recovery"),
        ("running", False, "needs_recovery"),
        ("succeeded", False, "needs_recovery"),
        ("failed", False, "failed"),
        ("cancelled", False, "cancelled"),
    ],
)
def test_provider_phase_and_local_observer_are_distinct(
    local, monkeypatch, provider_status, active, expected
):
    client, root, processes = local
    body = take(upload(client))
    client.post("/api/jobs", json=body)
    processes[0].returncode = None if active else 1
    rendered = root / "jobs" / body["request_id"] / "render"
    rendered.mkdir()
    (rendered / "job.json").write_text(
        json.dumps({"job_id": "existing-job", "backend": "self-hosted"})
    )

    @contextmanager
    def sdk(*args, **kwargs):
        yield SimpleNamespace(
            jobs=SimpleNamespace(get=lambda _: SimpleNamespace(status=provider_status))
        )

    monkeypatch.setattr(app, "sdk_client", sdk)
    result = client.get(f"/api/jobs/{body['request_id']}").json()
    assert result["status"] == expected
    assert result["active"] is active
    assert result["output_url"] is None
    assert len(processes) == 1


def test_unfinished_export_is_not_complete_or_downloadable(local, monkeypatch):
    client, root, processes = local
    body = take(upload(client))
    client.post("/api/jobs", json=body)
    rendered = root / "jobs" / body["request_id"] / "render"
    rendered.mkdir()
    (rendered / "job.json").write_text(
        json.dumps({"job_id": "existing-job", "backend": "self-hosted"})
    )
    partial = rendered / "reshoot.partial.mp4"
    partial.write_bytes(b"unfinished exporter output")

    @contextmanager
    def sdk(*args, **kwargs):
        yield SimpleNamespace(
            jobs=SimpleNamespace(get=lambda _: SimpleNamespace(status="succeeded"))
        )

    monkeypatch.setattr(app, "sdk_client", sdk)
    status_url = f"/api/jobs/{body['request_id']}"
    assert client.get(status_url).json()["status"] == "exporting"
    assert client.get(status_url + "/output").status_code == 404
    processes[0].returncode = 1
    assert client.get(status_url).json()["status"] == "needs_recovery"
    assert client.get(status_url + "/output").status_code == 404
    assert partial.read_bytes() == b"unfinished exporter output"
    assert len(processes) == 1


def test_source_preview_supports_range_and_rejects_short_upload(local, monkeypatch):
    client, _, processes = local
    source_id = upload(client)
    response = client.get(f"/api/sources/{source_id}", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"test"
    monkeypatch.setattr(
        app,
        "probe",
        lambda p: {"streams": [{"codec_type": "video"}], "format": {"duration": "2"}},
    )
    assert (
        client.post("/api/sources", files={"file": ("short.mp4", b"short")}).status_code
        == 400
    )
    assert not processes


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_webm_upload_has_a_real_mp4_preview_and_keeps_the_original(tmp_path):
    original = tmp_path / "camera.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=12:duration=5.1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=523:sample_rate=48000:duration=5.1",
            "-c:v",
            "libvpx",
            "-deadline",
            "realtime",
            "-c:a",
            "libopus",
            str(original),
        ],
        check=True,
    )
    root = tmp_path / "app"
    client = TestClient(app.create_app(root), base_url="http://localhost")
    response = client.post(
        "/api/sources",
        files={"file": ("camera.webm", original.read_bytes(), "video/webm")},
    )
    assert response.status_code == 200
    source_id = response.json()["source_id"]
    stored = root / "sources" / source_id
    assert (stored / "source.mp4").read_bytes() == original.read_bytes()
    preview = client.get(f"/api/sources/{source_id}")
    assert preview.headers["content-type"] == "video/mp4"
    assert preview.content[4:8] == b"ftyp"
    assert preview.content == (stored / "preview" / "source.mp4").read_bytes()
    info = probe(stored / "preview" / "source.mp4")
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (
        768,
        448,
        "24/1",
    )
    assert video["codec_name"] == "h264"
    assert audio["codec_name"] == "aac"


def test_preview_conversion_failure_leaves_no_source_or_render(local, monkeypatch):
    client, root, processes = local

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["ffmpeg"])

    monkeypatch.setattr(app, "prepare_source", fail)
    response = client.post("/api/sources", files={"file": ("camera.webm", b"fixture")})
    assert response.status_code == 400
    assert not list((root / "sources").iterdir())
    assert not processes


def test_disconnected_proxy_rejects_before_creating_take(local, monkeypatch):
    client, root, processes = local
    body = take(upload(client))

    def unavailable(*args, **kwargs):
        raise app.httpx.ConnectError("connection refused")

    monkeypatch.setattr(app.httpx, "get", unavailable)
    assert not client.get("/api/config").json()["connected"]
    assert client.post("/api/jobs", json=body).status_code == 503
    assert not list((root / "jobs").iterdir())
    assert not processes


def test_healthy_proxy_with_dead_upstream_is_not_a_ready_worker(local, monkeypatch):
    client, root, processes = local
    body = take(upload(client))

    def unavailable_upstream(url, **kwargs):
        if url.endswith("/system_stats"):
            raise app.httpx.ConnectError("upstream refused")
        return SimpleNamespace(status_code=200, json=dict)

    monkeypatch.setattr(app.httpx, "get", unavailable_upstream)
    assert not client.get("/api/config").json()["connected"]
    assert client.post("/api/jobs", json=body).status_code == 503
    assert not list((root / "jobs").iterdir())
    assert not processes


def test_upstream_preflight_requires_explicit_loopback_url(local, monkeypatch):
    client, _, processes = local
    monkeypatch.setenv("COMFY_UPSTREAM_URL", "https://external.invalid:443")
    assert not client.get("/api/config").json()["connected"]
    monkeypatch.delenv("COMFY_UPSTREAM_URL")
    assert not client.get("/api/config").json()["connected"]
    assert not processes


@pytest.mark.parametrize("payload", [["healthy"], {}, {"devices": "unknown"}])
def test_invalid_upstream_health_shape_does_not_report_ready(
    local, monkeypatch, payload
):
    client, _, _ = local
    monkeypatch.setattr(
        app.httpx,
        "get",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload),
    )
    assert not client.get("/api/config").json()["connected"]


def test_missing_job_id_requires_review_and_blocks_replacement(local):
    client, root, processes = local
    body = take(upload(client))
    client.post("/api/jobs", json=body)
    processes[0].returncode = 1
    rendered = root / "jobs" / body["request_id"] / "render"
    rendered.mkdir()
    (rendered / "job.json").write_text('{"job_id":null,"status":"submitting"}')
    assert client.get("/api/jobs").json()[0]["status"] == "needs_review"
    assert client.post(f"/api/jobs/{body['request_id']}/resume").status_code == 409
    assert len(processes) == 1


def test_export_contains_reproduction_inputs_not_private_runtime_state(local):
    client, root, _ = local
    body = take(upload(client))
    client.post("/api/jobs", json=body)
    render = root / "jobs" / body["request_id"] / "render"
    render.mkdir()
    (render / "source.mp4").write_bytes(b"normalized source fixture")
    (render / "workflow.json").write_text(
        '{"source":{"class_type":"LoadVideo","inputs":{"file":"source.mp4"}}}'
    )
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert settings["model"] == "ltx25"
    assert settings["prompt"] == body["prompt"]
    assert settings["source"] == "source.mp4"
    assert "source_id" not in settings and "base_url" not in settings
    source = client.get(f"/api/jobs/{body['request_id']}/source")
    assert source.status_code == 200
    assert source.content == b"normalized source fixture"
    assert 'filename="source.mp4"' in source.headers["content-disposition"]
    assert client.get(f"/api/jobs/{body['request_id']}/workflow").status_code == 200
    assert client.get(f"/api/jobs/{body['request_id']}/render.log").status_code == 404


def test_longer_video_takes_reach_the_renderer_and_settings(local, monkeypatch):
    client, _, processes = local
    monkeypatch.setattr(
        app,
        "probe",
        lambda p: {"streams": [{"codec_type": "video"}], "format": {"duration": "16"}},
    )
    source = upload(client)
    body = {**take(source), "seconds": 15}
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200
    arguments = processes[-1].args
    assert arguments[arguments.index("--seconds") + 1] == "15"
    assert "&seconds=15" in response.json()["source_url"]
    settings = client.get(f"/api/jobs/{body['request_id']}/settings").json()
    assert (settings["seconds"], settings["model_frames"]) == (15, 361)
    assert settings["export_frames"] == 360


@pytest.mark.parametrize(
    "change",
    [
        {"seconds": 7},
        {"seconds": 10, "render_profile": "single-pass-audio"},
        {"seconds": 10, "mode": "text", "source_id": None},
    ],
)
def test_longer_takes_are_video_to_video_two_pass_only(local, change):
    client, _, processes = local
    source = upload(client)
    assert client.post("/api/jobs", json={**take(source), **change}).status_code == 422
    assert not processes


def test_five_second_takes_omit_the_seconds_flag(local):
    client, _, processes = local
    source = upload(client)
    assert client.post("/api/jobs", json=take(source)).status_code == 200
    assert "--seconds" not in processes[-1].args
