import pytest
from PIL import Image

from aipg_cinema import flight, swap

LOCAL = {
    "diffusion_models": ["minimax_h3_fl2va_pruned_int8_convrot.safetensors"],
    "text_encoders": ["qwen3vl_32b_minimax_h3_int8_convrot.safetensors"],
    "vae": ["minimax_h3_video_vae_fp16.safetensors", swap.AUDIO_VAE],
    "loras": [flight.MOVES["orbit"]["lora"], flight.TURBO_LORA],
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


def test_orbit_pins_the_photo_as_first_and_last_frame():
    models = flight.recipe(LOCAL, "self-hosted", "orbit")
    workflow = flight.graph(models, "orbit", "portrait", seed=3, note="the red car")
    assert all(target in workflow for _, target in refs(workflow))
    i2v = workflow["i2v"]["inputs"]
    assert i2v["first_frame"] == ["photo", 0] and i2v["last_frame"] == ["photo", 0]
    assert (i2v["width"], i2v["height"]) == (768, 1344) and i2v["length"] == 124
    assert (
        "around the red car" in i2v["prompt"]
        and "Only the camera moves" in i2v["prompt"]
    )
    assert workflow["move"]["inputs"]["lora_name"] == flight.MOVES["orbit"]["lora"]
    assert workflow["move"]["inputs"]["strength_model"] == 1.0
    assert workflow["turbo"]["inputs"]["lora_name"] == flight.TURBO_LORA
    assert workflow["schedule"]["inputs"] == {
        "model": ["turbo", 0],
        "scheduler": "simple",
        "steps": flight.STEPS,
        "denoise": 1,
    }
    assert workflow["noise"]["inputs"]["noise_seed"] == 3
    assert "audio" not in workflow["video"]["inputs"]
    assert workflow["save-audio"]["inputs"]["audio"] == ["decode-audio", 0]


def test_fpv_keeps_only_the_first_frame_and_leads_with_the_trigger():
    listing = {**LOCAL, "loras": [flight.MOVES["fpv"]["lora"], flight.TURBO_LORA]}
    models = flight.recipe(listing, "self-hosted", "fpv")
    workflow = flight.graph(models, "fpv", "landscape", note="over the harbour")
    i2v = workflow["i2v"]["inputs"]
    assert "last_frame" not in i2v and i2v["first_frame"] == ["photo", 0]
    assert (i2v["width"], i2v["height"]) == (1344, 768)
    assert i2v["prompt"].startswith("camera motion.")
    assert "over the harbour" in i2v["prompt"]
    assert workflow["move"]["inputs"]["strength_model"] == 0.9


def test_speak_has_no_move_lora_and_puts_the_line_in_the_prompt():
    listing = {**LOCAL, "loras": [flight.TURBO_LORA]}
    models = flight.recipe(listing, "self-hosted", "speak")
    workflow = flight.graph(
        models, "speak", "portrait", note='Day four. Still no "coffee".'
    )
    assert "move" not in workflow
    assert workflow["turbo"]["inputs"]["model"] == ["model", 0]
    i2v = workflow["i2v"]["inputs"]
    assert "last_frame" not in i2v
    assert "says: \"Day four. Still no 'coffee'.\"" in i2v["prompt"]
    assert "lips in sync" in i2v["prompt"]
    with pytest.raises(ValueError):
        flight.prompt("speak", "")


def test_recipe_names_the_missing_move_lora_per_backend():
    cloud = {**LOCAL, "loras": [flight.TURBO_LORA]}
    with pytest.raises(flight.Unavailable) as missing:
        flight.recipe(cloud, "cloud", "orbit")
    assert missing.value.missing == [flight.MOVES["orbit"]["lora"]]
    assert "Nothing was submitted" in str(missing.value)
    with pytest.raises(flight.Unavailable) as both:
        flight.recipe({}, "self-hosted", "fpv")
    assert flight.MOVES["fpv"]["lora"] in both.value.missing
    assert flight.TURBO_LORA in both.value.missing
    with pytest.raises(ValueError):
        flight.recipe(LOCAL, "self-hosted", "dolly")
    with pytest.raises(ValueError):
        flight.prompt("orbit", "x" * 301)
    with pytest.raises(ValueError):
        flight.graph(flight.recipe(LOCAL, "self-hosted", "orbit"), "orbit", "wide")


def test_photo_is_centre_cropped_to_the_frame_shape(tmp_path):
    source = tmp_path / "wide.png"
    Image.new("RGB", (2000, 500), "red").save(source)
    out = flight.prepare_photo(source, tmp_path / "photo.png", "portrait")
    with Image.open(out) as image:
        assert image.size == (768, 1344)
    out = flight.prepare_photo(source, tmp_path / "square.png", "square")
    with Image.open(out) as image:
        assert image.size == (1024, 1024)


def test_flight_routes_validate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    # Readiness never reaches a backend in tests: the listing is unavailable.
    def offline(*args, **kwargs):
        raise app.httpx.ConnectError("offline")

    monkeypatch.setattr(app.person_swap, "available", offline)

    client = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    body = {"request_id": "a" * 32, "photo_id": "b" * 32}
    # Without the models nothing is sent and the reply says why.
    reply = client.post("/api/flights", json=body)
    assert (
        reply.status_code == 503 and "Nothing was submitted" in reply.json()["detail"]
    )
    assert (
        client.post("/api/flights", json={**body, "move": "dolly"}).status_code == 422
    )
    assert client.get("/api/flights/" + "c" * 32).status_code == 404
    assert client.get("/api/flights/" + "c" * 32 + "/output").status_code == 404
    ready = client.get("/api/flights/ready").json()["moves"]
    assert [m["id"] for m in ready] == ["orbit", "fpv", "speak"]
    assert all(m["ready"] is False and m["help"] for m in ready)
    assert client.get("/api/config").json()["flights"] == {
        "orbit": False,
        "fpv": False,
        "speak": False,
    }
