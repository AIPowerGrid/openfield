import io
import json
import zipfile

from aipg_cinema import comfybundle

WORKFLOW = {
    "source": {"class_type": "LoadVideo", "inputs": {"file": "source.mp4"}},
    "look": {"class_type": "LoadImage", "inputs": {"image": "look.png"}},
    "backbone": {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "ltx.safetensors", "weight_dtype": "default"},
    },
    "save": {
        "class_type": "SaveVideo",
        "inputs": {"video": ["source", 0], "image": ["look", 0], "seed": 7},
        "_meta": {"title": "Save"},
    },
}


def write_take(tmp_path):
    (tmp_path / "workflow.json").write_text(json.dumps(WORKFLOW))
    (tmp_path / "source.mp4").write_bytes(b"video")
    (tmp_path / "look.png").write_bytes(b"image")
    return tmp_path


def test_nodes_are_renumbered_and_links_rewritten():
    graph = comfybundle.numbered(WORKFLOW)
    assert list(graph) == ["1", "2", "3", "4"]
    assert graph["4"]["inputs"]["video"] == ["1", 0]
    assert graph["4"]["inputs"]["image"] == ["2", 0]
    assert graph["4"]["inputs"]["seed"] == 7
    # Original node names survive as titles.
    assert graph["1"]["_meta"]["title"] == "source"
    assert graph["4"]["_meta"]["title"] == "Save"


def test_bundle_holds_workflow_inputs_and_model_list(tmp_path):
    data = comfybundle.bundle(write_take(tmp_path), "openfield-abc")
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(archive.namelist()) == [
        "README.txt",
        "input/openfield-abc-look.png",
        "input/openfield-abc-source.mp4",
        "openfield-abc-workflow.json",
    ]
    graph = json.loads(archive.read("openfield-abc-workflow.json"))
    assert graph["1"]["inputs"]["file"] == "openfield-abc-source.mp4"
    assert graph["2"]["inputs"]["image"] == "openfield-abc-look.png"
    assert archive.read("input/openfield-abc-source.mp4") == b"video"
    readme = archive.read("README.txt").decode()
    assert "ComfyUI/models/diffusion_models/ltx.safetensors" in readme
    assert "ComfyUI/input/" in readme


def test_take_download_serves_the_comfyui_bundle(tmp_path):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    job = "a" * 32
    render = tmp_path / "web" / "jobs" / job / "render"
    render.mkdir(parents=True)
    (render.parent / "request.json").write_text(json.dumps({"mode": "video"}))
    write_take(render)
    response = client.get(f"/api/jobs/{job}/comfyui")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "openfield-aaaaaaaa-comfyui.zip" in response.headers["content-disposition"]
    assert (
        "openfield-aaaaaaaa-workflow.json"
        in zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    )
    (render / "workflow.json").unlink()
    assert client.get(f"/api/jobs/{job}/comfyui").status_code == 404
