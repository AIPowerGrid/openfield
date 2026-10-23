import json
import shutil
import subprocess
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from aipg_cinema import app

REAL_POPEN = subprocess.Popen
BRIEF = {
    "name": "Aqua Bottle",
    "tone": "premium",
    "setting": "a wet stone ledge beside a mountain spring",
    "benefits": ["Ice cold for hours"],
    "tagline": "Pure water, nothing else.",
    "cta": "Shop now",
}


def photo_bytes():
    image = Image.new("RGB", (600, 800), (235, 230, 220))
    ImageDraw.Draw(image).rounded_rectangle(
        (200, 100, 400, 700), 30, fill=(30, 90, 160)
    )
    data = BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


@pytest.fixture
def studio(tmp_path, monkeypatch):
    launched = []
    for name, value in {
        "COMFY_BASE_URL": "http://127.0.0.1:18291",
        "COMFY_UPSTREAM_URL": "http://127.0.0.1:18189",
        "COMFY_LOOK_BASE_URL": "http://127.0.0.1:18389",
        "COMFY_LOOK_UPSTREAM_URL": "http://127.0.0.1:18388",
    }.items():
        monkeypatch.setenv(name, value)
    models = {
        "UNETLoader": "unet_name",
        "CLIPLoader": "clip_name",
        "VAELoader": "vae_name",
    }

    def get(url, **kwargs):
        node = url.rsplit("/", 1)[-1]
        if node in models:
            names = [
                "flux-2-klein-4b.safetensors",
                "qwen_3_4b.safetensors",
                "flux2-vae.safetensors",
                "moss_image_sft_bf16.safetensors",
                "qwen3.5_9b_int8_convrot.safetensors",
            ]
            data = {node: {"input": {"required": {models[node]: [names]}}}}
        elif node == "SkipLayerGuidanceDiTSimple":
            fields = ("model", "single_layers", "double_layers")
            fields += ("start_percent", "end_percent")
            data = {node: {"input": {"required": dict.fromkeys(fields)}}}
        elif node in ("LTXVAddGuide", "LTXVCropGuides"):
            data = {node: {"input": {"required": {}}}}
        else:
            data = {"devices": []}
        return SimpleNamespace(
            status_code=200, json=lambda: data, raise_for_status=lambda: None
        )

    monkeypatch.setattr(app.httpx, "get", get)

    class Process:
        returncode = None

        def __init__(self, args, **kwargs):
            self.args, self.kwargs = args, kwargs
            launched.append(self)

        def poll(self):
            return self.returncode

    def popen(args, **kwargs):
        # Only background renders are faked; local FFmpeg packshots really run.
        if args[:2] == [app.sys.executable, "-m"]:
            return Process(args, **kwargs)
        return REAL_POPEN(args, **kwargs)

    monkeypatch.setattr(app.subprocess, "Popen", popen)
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", 2, max_looks=3),
        base_url="http://localhost",
    )
    return client, tmp_path, launched


def new_product(client):
    product = client.post(
        "/api/products", files={"file": ("p.png", photo_bytes(), "image/png")}
    )
    assert product.status_code == 200, product.text
    product_id = product.json()["product_id"]
    assert client.get(f"/api/products/{product_id}").status_code == 200
    created = client.post(
        "/api/projects",
        json={
            "title": "Aqua ad",
            "frame_format": "portrait",
            "structure": "product",
            "product": {"brief": BRIEF, "photo_ids": [product_id]},
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def test_product_project_is_planned_from_the_brief(studio):
    client, _, launched = studio
    project = new_product(client)
    # Calm pacing is the default: two gentle shots and the packshot.
    assert [shot["beat"] for shot in project["shots"]] == ["hook", "reveal", "payoff"]
    assert project["shots"][0]["camera"] == "push-in@1"
    assert project["caption_position"] == "upper"
    assert project["caption_style"] == "studio"
    assert project["product"]["packshot_shot_id"] == project["shots"][-1]["id"]
    assert [c["text"] for c in project["captions"]] == ["Meet Aqua Bottle"]
    assert not launched
    rejected = client.post(
        "/api/projects",
        json={"title": "x", "structure": "product"},
    )
    assert rejected.status_code == 422


def test_product_look_is_one_recoverable_job(studio):
    client, root, launched = studio
    project = new_product(client)
    shot = project["shots"][0]["id"]
    body = {"request_id": "a" * 32, "revision": project["revision"], "refine": True}
    look = client.post(
        f"/api/projects/{project['id']}/shots/{shot}/product-look", json=body
    )
    assert look.status_code == 200, look.text
    args = launched[-1].args
    assert args[2:4] == ["aipg_cinema.product", "look"]
    assert "--refine" in args and "--execute" in args
    assert (
        args[args.index("--prompt") + 1]
        == project["shots"][0]["draft"]["art_direction"]
    )
    assert "Aqua Bottle" not in args[args.index("--prompt") + 1]
    # The same ID returns the same job; a changed request cannot reuse it.
    again = client.post(
        f"/api/projects/{project['id']}/shots/{shot}/product-look", json=body
    )
    assert again.status_code == 200 and len(launched) == 1
    changed = client.post(
        f"/api/projects/{project['id']}/shots/{shot}/product-look",
        json=body | {"seed": 7},
    )
    assert changed.status_code == 409
    busy = client.post(
        f"/api/projects/{project['id']}/shots/{shot}/product-look",
        json=body | {"request_id": "b" * 32},
    )
    assert busy.status_code == 409 and len(launched) == 1
    packshot = project["product"]["packshot_shot_id"]
    wrong = client.post(
        f"/api/projects/{project['id']}/shots/{packshot}/product-look",
        json=body | {"request_id": "c" * 32},
    )
    assert wrong.status_code == 400

    # A finished look becomes the shot's opening image for an LTX take.
    launched[-1].returncode = 0
    render = root / "looks" / ("a" * 32) / "render"
    render.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1152, 2048)).save(render / "look.png")
    status = client.get(f"/api/product-looks/{'a' * 32}").json()
    assert status["status"] == "succeeded" and status["look_id"] == "a" * 32
    saved = client.get(f"/api/projects/{project['id']}").json()
    saved["shots"][0]["draft"]["look_id"] = "a" * 32
    saved = client.put(f"/api/projects/{project['id']}", json=saved)
    assert saved.status_code == 200, saved.text
    take = client.post(
        f"/api/projects/{project['id']}/shots/{shot}/generate",
        json={"request_id": "d" * 32, "revision": saved.json()["revision"]},
    )
    assert take.status_code == 200, take.text
    assert launched[-1].args[3:6] == ["generate", "--mode", "image"]
    launched[-1].returncode = 0
    # A later shot can continue from that finished look (same model/scene).
    later = saved.json()["shots"][1]["id"]
    continued = client.post(
        f"/api/projects/{project['id']}/shots/{later}/product-look",
        json={
            "request_id": "e" * 32,
            "revision": saved.json()["revision"],
            "continuity_look_id": "a" * 32,
        },
    )
    assert continued.status_code == 200, continued.text
    args = launched[-1].args
    assert args[args.index("--continuity") + 1].endswith("look.png")
    assert "second reference image" in args[args.index("--prompt") + 1]
    # Video renders keep the video worker URL even while look clients exist.
    assert launched[-1].kwargs["env"]["COMFY_BASE_URL"] == "http://127.0.0.1:18291"


def test_render_environment_is_snapshotted_under_the_client_lock(studio):
    client, _, launched = studio
    from aipg_cinema import cli

    project = new_product(client)
    body = {"request_id": "a" * 32, "revision": project["revision"]}
    acquired = []
    real = cli._CLIENT_CONFIG_LOCK

    class Lock:
        def __enter__(self):
            acquired.append(True)
            return real.__enter__()

        def __exit__(self, *error):
            return real.__exit__(*error)

    app_lock = app._CLIENT_CONFIG_LOCK
    app._CLIENT_CONFIG_LOCK = Lock()
    try:
        client.post(
            f"/api/projects/{project['id']}/shots/{project['shots'][0]['id']}"
            "/product-look",
            json=body,
        )
    finally:
        app._CLIENT_CONFIG_LOCK = app_lock
    assert acquired and "env" in launched[-1].kwargs


def test_cloud_looks_reject_moss_refinement(studio, tmp_path):
    client, _, _ = studio
    product = client.post(
        "/api/products", files={"file": ("p.png", photo_bytes(), "image/png")}
    ).json()["product_id"]
    cloud = TestClient(
        app.create_app(tmp_path, "self-hosted", look_engine="klein-cloud"),
        base_url="http://localhost",
    )
    project = cloud.post(
        "/api/projects",
        json={
            "structure": "product",
            "product": {"brief": BRIEF, "photo_ids": [product]},
        },
    ).json()
    response = cloud.post(
        f"/api/projects/{project['id']}/shots/{project['shots'][0]['id']}/product-look",
        json={"request_id": "a" * 32, "revision": project["revision"], "refine": True},
    )
    assert response.status_code == 422


def test_unreadable_product_photo_is_rejected(studio):
    client, root, _ = studio
    response = client.post(
        "/api/products", files={"file": ("p.png", b"not an image", "image/png")}
    )
    assert response.status_code == 400
    assert not any((root / "products").iterdir())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_packshot_is_a_free_local_take_selected_on_its_shot(studio):
    client, root, launched = studio
    project = new_product(client)
    packshot = project["product"]["packshot_shot_id"]
    blocked = client.post(
        f"/api/projects/{project['id']}/shots/{packshot}/generate",
        json={"request_id": "e" * 32, "revision": project["revision"]},
    )
    assert blocked.status_code == 400
    built = client.post(
        f"/api/projects/{project['id']}/shots/{packshot}/packshot",
        json={
            "request_id": "f" * 32,
            "revision": project["revision"],
            "accent": "#2f6fff",
        },
    )
    assert built.status_code == 200, built.text
    data = built.json()
    assert data["take"]["status"] == "succeeded" and data["take"]["output_url"]
    shot = next(s for s in data["project"]["shots"] if s["id"] == packshot)
    assert shot["selected_take_id"] == "f" * 32
    assert shot["draft"]["look_id"] == "f" * 32
    assert data["project"]["revision"] == project["revision"] + 1
    meta = json.loads(
        (root / "jobs" / ("f" * 32) / "render" / "packshot.json").read_text()
    )
    assert meta["ai_generated"] is False
    assert client.get("/api/config").json()["renders_used"] == 0
    assert not launched
    stale = client.post(
        f"/api/projects/{project['id']}/shots/{packshot}/packshot",
        json={"request_id": "1" * 32, "revision": project["revision"]},
    )
    assert stale.status_code == 409


def test_brief_draft_route_degrades_without_a_key(studio, monkeypatch):
    client, _, launched = studio
    monkeypatch.delenv("GRID_API_KEY", raising=False)
    product = client.post(
        "/api/products", files={"file": ("p.png", photo_bytes(), "image/png")}
    ).json()["product_id"]
    response = client.post(f"/api/products/{product}/brief", json={"name": "Lamp"})
    assert response.status_code == 503 and "manually" in response.json()["detail"]
    assert client.get("/api/config").json()["autobrief"] is False
    assert not launched


def test_brief_draft_route_returns_the_suggestion(studio, monkeypatch):
    client, _, _ = studio
    seen = []
    monkeypatch.setattr(
        app.autobrief,
        "suggest",
        lambda photo, name: (
            seen.append((photo.name, name)) or {"brief": {"name": name}}
        ),
    )
    product = client.post(
        "/api/products", files={"file": ("p.png", photo_bytes(), "image/png")}
    ).json()["product_id"]
    response = client.post(f"/api/products/{product}/brief", json={"name": "Lamp"})
    assert response.json() == {"brief": {"name": "Lamp"}}
    assert seen == [("product.png", "Lamp")]


def wav_bytes(seconds=12):
    import io
    import wave

    data = io.BytesIO()
    with wave.open(data, "wb") as stream:
        stream.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x00\x00\x00" * 48000 * seconds)
    return data.getvalue()


def test_generated_music_lies_under_the_whole_short(studio, monkeypatch):
    client, _, _ = studio
    project = new_product(client)
    calls = []

    def generate(body, key):
        calls.append((body, key))
        return wav_bytes(), {
            "model": "ace-step-v1.5-xl-turbo",
            "seconds": body["seconds"],
        }

    monkeypatch.setattr(app.music, "generate", generate)
    request = {"request_id": "9" * 32, "revision": project["revision"]}
    response = client.post(f"/api/projects/{project['id']}/music", json=request)
    assert response.status_code == 200, response.text
    saved = response.json()["project"]
    total = sum(s["trim_end"] - s["trim_start"] for s in saved["shots"])
    assert saved["music"]["audio_id"] == "9" * 32
    assert saved["music"]["duration_frames"] == total
    assert all(shot["volume"] == 0 for shot in saved["shots"])
    body = calls[0][0]
    assert body["model"] == "ace-step-v1.5-xl-turbo" and "no vocals" in body["prompt"]
    assert body["seconds"] >= total / 24
    again = client.post(f"/api/projects/{project['id']}/music", json=request)
    assert again.status_code == 409 and len(calls) == 1


def test_music_failure_leaves_the_project_unchanged(studio, monkeypatch):
    client, _, _ = studio
    project = new_product(client)

    def fail(body, key):
        raise app.music.MusicError("Music generation failed. Nothing was retried.")

    monkeypatch.setattr(app.music, "generate", fail)
    response = client.post(
        f"/api/projects/{project['id']}/music",
        json={"request_id": "8" * 32, "revision": project["revision"]},
    )
    assert response.status_code == 503
    assert client.get(f"/api/projects/{project['id']}").json()["music"] is None


def test_template_projects_and_saved_templates(studio):
    client, _, _ = studio
    listed = client.get("/api/templates").json()
    assert {t["id"] for t in listed} >= {"aipg-tee", "aipg-mug", "aipg-bottle"}
    assert client.get(listed[0]["preview_url"]).status_code == 200
    product = client.post(
        "/api/products", files={"file": ("p.png", photo_bytes(), "image/png")}
    ).json()["product_id"]
    created = client.post(
        "/api/projects",
        json={
            "structure": "product",
            "template_id": "aipg-bottle",
            "product": {"brief": BRIEF | {"tone": "calm"}, "photo_ids": [product]},
        },
    ).json()
    assert created["product"]["brief"]["tone"] == "bold"  # the template decides
    assert created["product"]["brief"]["hook"] == BRIEF.get("hook", "")
    assert [s["camera"] for s in created["shots"]] == ["push-in@1", "pull-back@1", None]
    saved = client.post(f"/api/projects/{created['id']}/template").json()
    assert saved["id"].startswith("user-") and not saved["builtin"]
    assert any(t["id"] == saved["id"] for t in client.get("/api/templates").json())
    missing = client.post(
        "/api/projects",
        json={
            "structure": "product",
            "template_id": "nope-nope",
            "product": {"brief": BRIEF, "photo_ids": [product]},
        },
    )
    assert missing.status_code == 404
    config = client.get("/api/config").json()
    assert "(est.)" in config["estimates"]["take"]["label"]


def test_retry_safe_creation_plans_a_template_short_once(studio):
    client, _, launched = studio
    product = client.post(
        "/api/products", files={"file": ("p.png", photo_bytes(), "image/png")}
    ).json()["product_id"]
    path = "/api/project-creations/" + "d" * 32
    body = {
        "title": "Mug ad",
        "structure": "product",
        "template_id": "aipg-bottle",
        "product": {"brief": BRIEF | {"tone": "calm"}, "photo_ids": [product]},
    }
    first = client.post(path, json=body)
    assert first.status_code == 200, first.text
    project = first.json()["project"]
    assert project["product"]["brief"]["tone"] == "bold"  # the template decides
    assert [s["camera"] for s in project["shots"]] == ["push-in@1", "pull-back@1", None]
    # The saved request is the user's own, so a replay matches and changes nothing.
    assert first.json()["request"]["product"]["brief"]["tone"] == "calm"
    replay = client.post(path, json=body)
    assert replay.status_code == 200
    assert replay.json()["project"] == project
    assert client.get(path).json()["project"] == project
    assert not launched


def test_openfield_scripts_and_fonts_are_served(studio):
    client, _, _ = studio
    for path in ("/home.js", "/presetbrowser.js", "/autopilot.js", "/styles.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript")
    font = client.get("/fonts/Michroma-Regular.ttf")
    assert font.status_code == 200 and len(font.content) > 10_000


def test_showcase_examples_are_bundled_and_credited(studio):
    client, _, _ = studio
    examples = client.get("/showcase/showcase.json").json()
    credits = examples.pop("credits")
    assert credits and all(
        c["license"] and c["url"].startswith("https://") for c in credits
    )
    for feature, example in examples.items():
        assert feature in {"reshoot", "product", "animate", "idea", "audio", "story"}
        assert client.get(f"/showcase/{example['video']}.mp4").status_code == 200
        assert client.get(f"/showcase/{example['video']}.jpg").status_code == 200
        segments = example.get("segments", [])
        assert [s["start"] for s in segments] == sorted(s["start"] for s in segments)
