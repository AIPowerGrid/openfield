import json
from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from comfy_sdk.workflows import WorkflowFactory
from PIL import Image

from aipg_cinema import cli, look


@pytest.mark.parametrize("denoise", [0.4, 0.65, 0.75])
def test_native_graph_keeps_qualified_models_and_sampling(denoise):
    graph = look.graph("Copper surfaces and warm light", 314, denoise)
    assert WorkflowFactory().from_json(graph).json == graph
    assert graph["model"]["inputs"]["unet_name"] == "moss_image_sft_bf16.safetensors"
    assert graph["clip"]["inputs"]["type"] == "moss_image"
    assert graph["sample"]["inputs"] == {
        "model": ["negative-skip", 0],
        "seed": 314,
        "steps": 50,
        "cfg": 3,
        "sampler_name": "euler",
        "scheduler": "simple",
        "denoise": denoise,
        "positive": ["positive", 0],
        "negative": ["negative", 0],
        "latent_image": ["encode", 0],
    }
    assert "spheres" not in graph["negative"]["inputs"]["text"]
    assert graph["negative-skip"] == {
        "class_type": "SkipLayerGuidanceDiTSimple",
        "inputs": {
            "model": ["model", 0],
            "double_layers": "",
            "single_layers": "22",
            "start_percent": 0,
            "end_percent": 1,
        },
    }


@pytest.mark.parametrize("denoise", [float("nan"), float("inf"), 0, -1, 1.1])
def test_invalid_denoise_is_not_submitted(denoise):
    with pytest.raises(ValueError):
        look.graph("Warm light", denoise=denoise)


def test_look_requires_execution_and_its_own_endpoint(tmp_path, monkeypatch):
    directory = tmp_path / "render"
    monkeypatch.delenv("COMFY_LOOK_BASE_URL", raising=False)
    command = [
        "look",
        str(tmp_path / "missing.mp4"),
        "--prompt",
        "Warm light",
        "--run-dir",
        str(directory),
    ]
    assert cli.main(command) == 1
    assert cli.main([*command, "--execute"]) == 1
    assert not directory.exists()


def test_sdk_look_credentials_are_not_video_or_cloud_credentials(monkeypatch):
    monkeypatch.setenv("COMFY_API_KEY", "test-cloud-secret")
    monkeypatch.setenv("COMFY_LOCAL_TOKEN", "test-video-secret")
    monkeypatch.setenv("COMFY_LOOK_LOCAL_TOKEN", "test-look-secret")
    monkeypatch.setenv("COMFY_BASE_URL", "https://cloud.comfy.org")
    captured = []

    def factory(**kwargs):
        captured.append((kwargs["api_key"], cli.os.environ.get("COMFY_API_KEY")))
        return SimpleNamespace()

    monkeypatch.setattr(cli, "Comfy", factory)
    cli.configured_client("self-hosted", "http://127.0.0.1:18389", "look")
    assert captured == [("test-look-secret", None)]
    assert cli.os.environ["COMFY_BASE_URL"] == "https://cloud.comfy.org"
    assert cli.os.environ["COMFY_API_KEY"] == "test-cloud-secret"
    with pytest.raises(ValueError, match="self-hosted"):
        cli.configured_client("cloud", None, "look")


@pytest.mark.parametrize("frame_index", [0, 120])
@pytest.mark.parametrize("kind", ["video", "image", "text"])
@pytest.mark.parametrize("engine", ["moss", "klein-cloud"])
@pytest.mark.parametrize(
    "frame_format,size",
    [("landscape", (1536, 896)), ("portrait", (1152, 2048)), ("square", (1280, 1280))],
)
def test_real_sdk_shape_look_output_and_same_job_recovery(
    tmp_path, monkeypatch, frame_index, engine, frame_format, size, kind
):
    source = tmp_path / "camera.mp4"
    source.write_bytes(b"synthetic fixture")
    content = BytesIO()
    Image.new("RGB", (1344, 768), "coral").save(content, format="PNG")
    if kind == "image":
        source.write_bytes(content.getvalue())
    calls = []

    class Output:
        name = "image/fixture.png"
        content_type = "image/png"

        def to_file(self, path):
            path.write_bytes(content.getvalue())

    class Job:
        id, status = "existing-look-job", "succeeded"

        def wait(self, timeout):
            pass

        def get_outputs(self, node):
            assert node == "save"
            return [Output()]

    class Client:
        workflows = WorkflowFactory()
        assets = SimpleNamespace(from_file=lambda path: path)
        jobs = SimpleNamespace(get=lambda job_id: calls.append(job_id) or Job())

        def submit(self, workflow, **kwargs):
            calls.append("submit")
            return Job()

    @contextmanager
    def sdk(backend, base_url, *, credential_scope):
        assert (backend, base_url, credential_scope) == (
            "cloud" if engine == "klein-cloud" else "self-hosted",
            "https://cloud.comfy.org"
            if engine == "klein-cloud"
            else "http://127.0.0.1:18389",
            "cloud-look" if engine == "klein-cloud" else "look",
        )
        yield Client()

    monkeypatch.setattr(cli, "sdk_client", sdk)
    monkeypatch.setenv("COMFY_LOOK_BASE_URL", "http://127.0.0.1:18389")
    from aipg_cinema import reshoot

    monkeypatch.setattr(reshoot, "prepare_source", lambda path, root, **options: path)

    def frame(path, root, index):
        assert index == frame_index
        target = root / "source.png"
        target.write_bytes(content.getvalue())
        return target

    monkeypatch.setattr(look, "source_frame", frame)
    root = tmp_path / "look"
    command = [
        "look",
        *([str(source)] if kind != "text" else []),
        "--look-input",
        kind,
        "--prompt",
        "Warm light",
        "--frame-index",
        str(frame_index),
        "--engine",
        engine,
        "--run-dir",
        str(root),
        "--execute",
        "--format",
        frame_format,
        "--source-start",
        "2.5" if kind == "video" else "0",
    ]
    assert cli.main(command) == 0
    with Image.open(root / "look.png") as image:
        assert image.size == size
    state = json.loads((root / "job.json").read_text())
    assert state["look_render"] is True
    assert state["negative_skip_layers"] == ([] if engine == "klein-cloud" else [22])
    assert state["denoise"] == (
        None if engine == "klein-cloud" else 1 if kind == "text" else 0.65
    )
    assert state["source_frame_index"] == (frame_index if kind == "video" else None)
    assert (root / "source.png").exists() == (kind != "text")
    assert state["frame_format"] == frame_format
    assert state["source_start"] == (2.5 if kind == "video" else 0)
    assert state["look_output"] == "look.png"
    assert cli.main(command) == 1
    assert cli.main(["resume", str(root)]) == 0
    assert calls == ["submit", "existing-look-job"]


def test_klein_uses_the_qualified_four_step_reference_graph():
    graph = look.klein_graph("Warm copper light", 77)
    assert WorkflowFactory().from_json(graph).json == graph
    assert graph["model"]["inputs"]["unet_name"] == "flux-2-klein-4b-fp8.safetensors"
    assert graph["clip"]["inputs"]["clip_name"] == "qwen_3_4b.safetensors"
    assert graph["schedule"]["inputs"]["steps"] == 4
    assert graph["guider"]["inputs"]["cfg"] == 1
    assert graph["noise"]["inputs"]["noise_seed"] == 77
    assert graph["empty"]["inputs"]["batch_size"] == 1
    for name in ("ref-positive", "ref-negative"):
        assert graph[name]["class_type"] == "ReferenceLatent"
        assert graph[name]["inputs"]["latent"] == ["encode", 0]
    assert not any("denoise" in value["inputs"] for value in graph.values())
    assert "negative-skip" not in graph


@pytest.mark.parametrize("prompt,seed", [("", 42), ("x" * 4001, 42), ("Warm", -1)])
def test_klein_invalid_direction_is_rejected_before_execution(prompt, seed):
    with pytest.raises(ValueError):
        look.klein_graph(prompt, seed)


def test_cloud_look_credentials_are_pinned_and_never_local(monkeypatch):
    monkeypatch.setenv("COMFY_BASE_URL", "http://127.0.0.1:18291")
    monkeypatch.setenv("COMFY_API_KEY", "test-cloud-only")
    monkeypatch.setenv("COMFY_LOOK_LOCAL_TOKEN", "test-moss-only")
    calls = []

    def factory(**kwargs):
        calls.append((kwargs, cli.os.environ["COMFY_BASE_URL"]))
        return SimpleNamespace()

    monkeypatch.setattr(cli, "Comfy", factory)
    cli.configured_client("cloud", "https://cloud.comfy.org", "cloud-look")
    assert calls[0][0]["api_key"] is None
    assert calls[0][1] == "https://cloud.comfy.org"
    assert cli.os.environ["COMFY_BASE_URL"] == "http://127.0.0.1:18291"
    with pytest.raises(ValueError):
        cli.configured_client("cloud", "https://outside.invalid", "cloud-look")
    with pytest.raises(ValueError):
        cli.configured_client("self-hosted", "http://127.0.0.1:18291", "cloud-look")
    assert len(calls) == 1
    assert cli.os.environ["COMFY_API_KEY"] == "test-cloud-only"


def test_cli_never_silently_discards_klein_denoise(tmp_path):
    directory = tmp_path / "look"
    assert (
        cli.main(
            [
                "look",
                str(tmp_path / "source.mp4"),
                "--engine",
                "klein-cloud",
                "--prompt",
                "Copper light",
                "--denoise",
                "0.65",
                "--run-dir",
                str(directory),
                "--execute",
            ]
        )
        == 1
    )
    assert not directory.exists()


def test_closing_source_frame_uses_an_exact_normalized_frame(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        look.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    assert (
        look.source_frame(tmp_path / "source.mp4", tmp_path, 120)
        == tmp_path / "source.png"
    )
    command, options = calls[0]
    # Every FFmpeg call is bounded; a stuck decode cannot hold the request.
    assert options["timeout"] == 120 and options["check"] is True
    assert command[command.index("-vf") + 1] == "select=eq(n\\,120)"
    with pytest.raises(ValueError, match="opening frame or the last frame"):
        look.source_frame(tmp_path / "source.mp4", tmp_path, -1)
    assert len(calls) == 1
