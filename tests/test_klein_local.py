from fastapi.testclient import TestClient

from aipg_cinema import app
from aipg_cinema.look import klein_graph


def test_klein_graph_names_the_worker_file():
    assert klein_graph("Ink")["model"]["inputs"]["unet_name"] == (
        "flux-2-klein-4b-fp8.safetensors"
    )
    local = klein_graph("Ink", unet_name="flux-2-klein-4b.safetensors")
    assert local["model"]["inputs"]["unet_name"] == "flux-2-klein-4b.safetensors"


def test_self_hosted_klein_looks_take_no_denoise(tmp_path):
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", look_engine="klein"),
        base_url="http://localhost",
    )
    config = client.get("/api/config").json()
    assert config["look_engine"] == "klein"
    assert config["look_model"] == "FLUX.2 Klein 4B"
    assert set(config["look_presets"]) == {"warm", "blue"}
    body = {
        "request_id": "b" * 32,
        "look_input": "text",
        "prompt": "A paper boat",
        "denoise": 1.0,
    }
    response = client.post("/api/look-jobs", json=body)
    assert response.status_code == 422
    assert "reference conditioning" in response.json()["detail"]


def test_a_style_image_adds_a_second_reference_latent():
    graph = klein_graph("Ink", style_image=True)
    assert graph["style"]["inputs"]["image"] == "style.png"
    assert graph["style-positive"]["inputs"]["conditioning"] == ["ref-positive", 0]
    assert graph["guider"]["inputs"]["positive"] == ["style-positive", 0]
    assert graph["guider"]["inputs"]["negative"] == ["style-negative", 0]
    import pytest

    with pytest.raises(ValueError):
        klein_graph("Ink", from_image=False, style_image=True)


def test_style_images_need_klein_and_a_video_frame(tmp_path):
    from aipg_cinema.contracts import LookRequest

    base = {"request_id": "b" * 32, "prompt": "Ink", "style_image_id": "c" * 32}
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LookRequest(**base, look_input="text")
    client = TestClient(
        app.create_app(tmp_path, "self-hosted"), base_url="http://localhost"
    )
    response = client.post(
        "/api/look-jobs",
        json={**base, "source_id": "d" * 32, "denoise": 0.65},
    )
    assert response.status_code in (404, 422)
    if response.status_code == 422:
        assert "Klein" in response.json()["detail"]


def test_up_to_three_references_chain_in_order():
    graph = klein_graph("Add it", style_image=3)
    assert graph["style-2-positive"]["inputs"]["conditioning"] == ["style-positive", 0]
    assert graph["style-3-positive"]["inputs"]["conditioning"] == [
        "style-2-positive",
        0,
    ]
    assert graph["guider"]["inputs"]["positive"] == ["style-3-positive", 0]
    assert graph["style-3"]["inputs"]["image"] == "style-3.png"
    import pytest

    with pytest.raises(ValueError):
        klein_graph("Add it", style_image=4)


def test_add_to_video_contracts():
    import pytest
    from pydantic import ValidationError

    from aipg_cinema.contracts import LookRequest, TakeRequest

    base = {"request_id": "b" * 32, "prompt": "Add it", "source_id": "d" * 32}
    assert LookRequest(**base, reference_ids=["c" * 32, "e" * 32]).reference_ids
    with pytest.raises(ValidationError):
        LookRequest(**base, reference_ids=["c" * 32] * 4)
    with pytest.raises(ValidationError):
        LookRequest(**base, reference_ids=["not-an-id"])
    take = {"request_id": "a" * 32, "prompt": "Add it", "source_id": "d" * 32}
    assert TakeRequest(**take, motion_strength=0.6).motion_strength == 0.6
    with pytest.raises(ValidationError):
        TakeRequest(**take, motion_strength=0.3)
    with pytest.raises(ValidationError):
        TakeRequest(**{**take, "source_id": None, "mode": "text"}, motion_strength=0.6)
