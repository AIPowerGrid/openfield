import pytest

from aipg_cinema import replace


def test_prompts_rebuild_the_person_and_follow_the_voice():
    assert "Remove the person completely" in replace.PLATE
    assert "exact person from the first image" in replace.PLACE
    assert "fully clothed" in replace.PLACE and "{note}" in replace.PLACE
    assert "supplied speech" in replace.TALK


def test_replacement_routes_validate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    # Readiness never reaches a backend in tests: the listing is unavailable.
    def offline(*args, **kwargs):
        raise app.httpx.ConnectError("offline")

    monkeypatch.setattr(app.person_swap, "available", offline)

    body = {"request_id": "a" * 32, "source_id": "b" * 32, "photo_id": "c" * 32}
    moss = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    # The default engine is the H3 swap; without its models nothing is sent.
    swap = moss.post("/api/replacements", json=body)
    assert swap.status_code == 503 and "Nothing was submitted" in swap.json()["detail"]
    rebuild = {**body, "engine": "rebuild"}
    assert moss.post("/api/replacements", json=rebuild).status_code == 409
    klein = TestClient(
        app.create_app(tmp_path / "b", look_engine="klein"), base_url="http://localhost"
    )
    assert klein.post("/api/replacements", json=rebuild).status_code == 404
    assert (
        klein.post("/api/replacements", json={**body, "engine": "x"}).status_code == 422
    )
    ready = klein.get("/api/replacements/ready")
    assert ready.status_code == 200
    assert ready.json()["swap"] is False and ready.json()["rebuild"] is True
    assert klein.get("/api/config").json()["replace"]["swap"] is False
    assert (
        klein.post("/api/replacements", json={**body, "note": "x" * 301}).status_code
        == 422
    )
    assert klein.get("/api/replacements/" + "d" * 32).status_code == 404
    assert klein.get("/api/replacements/" + "d" * 32 + "/output").status_code == 404


def test_photo_looks_may_take_reference_images():
    from aipg_cinema.contracts import LookRequest

    look = LookRequest(
        request_id="a" * 32,
        look_input="image",
        image_id="b" * 32,
        reference_ids=["c" * 32],
        prompt="Place this person",
        denoise=None,
    )
    assert look.reference_ids == ["c" * 32]


def test_background_engine_uses_the_swap_route(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    listing = {
        "diffusion_models": ["minimax_h3_ref2va_pruned_int8_convrot.safetensors"],
        "text_encoders": ["qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"],
        "vae": [
            "minimax_h3_video_vae_int8_convrot.safetensors",
            "minimax_h3_audio_vae_fp32.safetensors",
        ],
        "loras": ["minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"],
    }
    monkeypatch.setattr(app.person_swap, "available", lambda *a, **k: listing)
    client = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    ready = client.get("/api/replacements/ready").json()
    # Cloud's own files are enough for the background; the person swap still
    # needs the imported LoRA.
    assert ready["background"] is True and ready["swap"] is False
    assert "h3_character_swap" in ready["swap_help"]
    body = {"request_id": "a" * 32, "source_id": "b" * 32, "photo_id": "c" * 32}
    assert (
        client.post(
            "/api/replacements", json={**body, "engine": "background"}
        ).status_code
        == 404
    )
    assert client.post("/api/replacements", json=body).status_code == 503


def test_scene_engine_needs_klein_and_a_place(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from aipg_cinema import app
    from aipg_cinema.contracts import PersonReplacement

    def offline(*args, **kwargs):
        raise app.httpx.ConnectError("offline")

    monkeypatch.setattr(app.person_swap, "available", offline)
    body = {
        "request_id": "a" * 32,
        "source_id": "b" * 32,
        "engine": "scene",
        "note": "a beach at sunset",
    }
    moss = TestClient(app.create_app(tmp_path / "a"), base_url="http://localhost")
    assert moss.post("/api/replacements", json=body).status_code == 409
    klein = TestClient(
        app.create_app(tmp_path / "b", look_engine="klein"), base_url="http://localhost"
    )
    assert klein.post("/api/replacements", json=body).status_code == 404
    assert klein.post("/api/replacements", json={**body, "note": ""}).status_code == 422
    with pytest.raises(ValueError):
        PersonReplacement(request_id="a" * 32, source_id="b" * 32)
    assert PersonReplacement(**body).photo_id is None
