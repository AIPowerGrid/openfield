import subprocess
from types import SimpleNamespace

import pytest

from aipg_cinema import remove

LISTING = {
    "diffusion_models": ["wan2.1_vace_1.3B_fp16.safetensors"],
    "text_encoders": ["umt5_xxl_fp16.safetensors"],
    "vae": [remove.VAE],
    "checkpoints": [remove.SAM],
}


def refs(workflow):
    for key, item in workflow.items():
        for value in item["inputs"].values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
            ):
                yield key, value[0]


def test_find_stage_tracks_the_target_and_previews_the_mask():
    workflow = remove.graph(None, "find", " the cup ", "portrait")
    assert all(target in workflow for _, target in refs(workflow))
    assert workflow["what"]["inputs"]["text"] == "the cup"
    assert workflow["track"]["inputs"]["conditioning"] == ["what", 0]
    assert workflow["grown"]["inputs"]["expand"] == remove.EXPAND
    assert workflow["preview"]["inputs"]["image2"] == ["mask-image", 0]
    assert workflow["save-mask"]["class_type"] == "SaveVideo"
    assert "vace" not in workflow and "sample" not in workflow


def test_remove_stage_blacks_out_the_region_and_samples_with_vace():
    models = remove.recipe(LISTING, "self-hosted")
    workflow = remove.graph(
        models, "remove", "the cup", "landscape", 9, "A kitchen", 30
    )
    assert all(target in workflow for _, target in refs(workflow))
    assert workflow["grown"]["inputs"]["expand"] == 30
    control = workflow["control"]["inputs"]
    assert control["destination"] == ["parts", 0]
    assert control["source"] == ["fill", 0] and control["mask"] == ["grown", 0]
    assert workflow["fill"]["inputs"]["color"] == remove.GREY
    vace = workflow["vace"]["inputs"]
    assert (vace["width"], vace["height"], vace["length"]) == (848, 480, 121)
    assert (121 - 1) % 4 == 0 and all(side % 16 == 0 for side in (848, 480))
    assert vace["control_video"] == ["control", 0]
    assert vace["control_masks"] == ["grown", 0]
    assert "reference_image" not in vace
    assert workflow["positive"]["inputs"]["text"].startswith(
        "A kitchen. In the marked area there is only the plain background"
    )
    assert "the cup" not in workflow["positive"]["inputs"]["text"]
    filled = remove.graph(models, "remove", "the cup", "landscape", fill="bare wood")
    assert "there is bare wood," in filled["positive"]["inputs"]["text"]
    assert workflow["negative"]["inputs"]["text"] == "the cup, " + remove.NEGATIVE
    assert workflow["clip"]["inputs"]["type"] == "wan"
    assert (
        workflow["model"]["inputs"]["unet_name"] == "wan2.1_vace_1.3B_fp16.safetensors"
    )
    assert workflow["sample"]["inputs"]["seed"] == 9
    assert workflow["sample"]["inputs"]["latent_image"] == ["vace", 2]
    assert workflow["trim"]["inputs"]["trim_amount"] == ["vace", 3]
    assert workflow["decode"]["inputs"]["samples"] == ["trim", 0]
    assert "audio" not in workflow["video"]["inputs"]


def test_recipe_and_bounds():
    with pytest.raises(remove.Unavailable) as missing:
        remove.recipe({**LISTING, "checkpoints": []}, "cloud")
    assert missing.value.missing == [remove.SAM]
    with pytest.raises(remove.Unavailable) as empty:
        remove.recipe({}, "self-hosted")
    assert set(empty.value.missing) == {
        "wan2.1_vace_1.3B_fp16.safetensors",
        "umt5_xxl_fp16.safetensors",
        remove.VAE,
        remove.SAM,
    }
    cloud = remove.recipe(
        {**LISTING, "text_encoders": ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"]},
        "cloud",
    )
    assert cloud.clip == "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    with pytest.raises(ValueError):
        remove.graph(None, "paint", "the cup", "portrait")
    with pytest.raises(ValueError):
        remove.graph(None, "find", "x", "portrait")
    with pytest.raises(ValueError):
        remove.graph(None, "find", "the cup", "wide")
    with pytest.raises(ValueError):
        remove.graph(None, "find", "the cup", "portrait", expand=101)
    with pytest.raises(ValueError):
        remove.graph(
            remove.recipe(LISTING, "cloud"),
            "remove",
            "the cup",
            "portrait",
            note="x" * 301,
        )
    with pytest.raises(ValueError, match="model names"):
        remove.graph(None, "remove", "the cup", "portrait")


@pytest.mark.skipif(
    subprocess.run(["ffmpeg", "-version"], capture_output=True, check=False).returncode
    != 0,
    reason="ffmpeg",
)
def test_prepare_gives_exactly_121_frames_at_vace_size(tmp_path):
    source = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "5", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(source)],
        check=True,
    )  # fmt: skip
    prepared = remove.prepare(source, tmp_path, "landscape")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,nb_read_frames", "-of", "csv=p=0",
         str(prepared)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert probe.stdout.strip() == "848,480,121"


def test_removal_routes_validate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    # Readiness never reaches a backend in tests: the listing is unavailable.
    def offline(*args, **kwargs):
        raise app.httpx.ConnectError("offline")

    monkeypatch.setattr(app.person_swap, "available", offline)

    client = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    body = {"request_id": "a" * 32, "source_id": "b" * 32, "target": "the cup"}
    reply = client.post("/api/removals", json=body)
    assert (
        reply.status_code == 503 and "Nothing was submitted" in reply.json()["detail"]
    )
    assert client.post("/api/removals", json={**body, "target": "x"}).status_code == 422
    assert client.post("/api/removals", json={**body, "expand": 500}).status_code == 422
    assert client.get("/api/removals/" + "c" * 32).status_code == 404
    assert client.post("/api/removals/" + "c" * 32 + "/remove").status_code == 404
    assert client.get("/api/removals/" + "c" * 32 + "/mask").status_code == 404
    ready = client.get("/api/removals/ready").json()
    assert ready["ready"] is False and ready["help"]
    assert client.get("/api/config").json()["removal"] is False


def test_remover_engine_uses_the_wrapper_nodes_without_a_prompt():
    listing = {
        "diffusion_models": [remove.REMOVER],
        "vae": [remove.VAE],
        "checkpoints": [remove.SAM],
    }
    models = remove.recipe(listing, "cloud", "remover")
    assert models.engine == "remover" and models.clip == ""
    workflow = remove.graph(models, "remove", "the spoon", "portrait", 7, "", 40)
    assert all(target in workflow for _, target in refs(workflow))
    assert "positive" not in workflow and "vace" not in workflow
    assert workflow["fill"]["inputs"]["color"] == remove.GREY
    assert workflow["latents"]["inputs"]["image"] == ["control", 0]
    assert workflow["mask-latents"]["inputs"]["image"] == ["mask-image", 0]
    embeds = workflow["embeds"]["inputs"]
    assert embeds["latents"] == ["latents", 0] and embeds["mask_latents"] == [
        "mask-latents",
        0,
    ]
    assert embeds["num_frames"] == 121 and (embeds["width"], embeds["height"]) == (
        480,
        848,
    )
    sample = workflow["sample"]["inputs"]
    assert (sample["steps"], sample["cfg"], sample["scheduler"], sample["seed"]) == (
        12,
        1.0,
        "unipc",
        7,
    )
    assert workflow["model"]["inputs"]["model"] == remove.REMOVER
    with pytest.raises(remove.Unavailable) as missing:
        remove.recipe({**listing, "diffusion_models": []}, "self-hosted", "remover")
    assert missing.value.missing == [remove.REMOVER]
    with pytest.raises(ValueError):
        remove.recipe(listing, "cloud", "lama")


def test_remover_node_check_asks_a_local_worker(monkeypatch):
    seen = []

    def get(url, **kwargs):
        seen.append(url)
        return SimpleNamespace(status_code=200, json=lambda: {remove.REMOVER_NODE: {}})

    monkeypatch.setattr(remove.httpx, "get", get)
    assert remove.remover_node_present("self-hosted", "http://127.0.0.1:18189") is True
    assert seen == ["http://127.0.0.1:18189/object_info/" + remove.REMOVER_NODE]
    assert remove.remover_node_present("cloud") is True and len(seen) == 1
    monkeypatch.setattr(
        remove.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    assert remove.remover_node_present("self-hosted", "http://127.0.0.1:18189") is False
