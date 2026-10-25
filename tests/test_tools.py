import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aipg_cinema import app, tools
from aipg_cinema.reshoot import probe


def test_fps_boost_doubles_frames_with_rife():
    graph = tools.graph("fps-boost")
    assert graph["interp-model"]["inputs"]["model_name"] == "rife_v4.26.safetensors"
    assert graph["interpolate"]["inputs"]["multiplier"] == 2
    assert graph["video"]["inputs"]["fps"] == 48
    # The source's sound is carried through.
    assert graph["video"]["inputs"]["audio"] == ["frames", 1]


def test_background_removal_composites_or_outputs_a_matte():
    green = tools.graph("remove-background")
    assert green["plate"]["inputs"]["color"] == 0x00B140
    assert green["composite"]["inputs"]["mask"] == ["mask", 0]
    matte = tools.graph("remove-background", background="matte")
    assert matte["matte"]["class_type"] == "MaskToImage" and "plate" not in matte
    with pytest.raises(ValueError):
        tools.graph("remove-background", background="pink")
    with pytest.raises(ValueError):
        tools.graph("depth")


def test_every_model_tool_uses_core_nodes_and_one_save():
    for tool in tools.MODELS:
        graph = tools.graph(tool)
        assert graph["source"]["class_type"] == "LoadVideo"
        assert [k for k, n in graph.items() if n["class_type"] == "SaveVideo"] == [
            "save"
        ]


def clip(path, width=320, height=180):
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def test_reframe_runs_locally_and_keeps_sound(tmp_path):
    source = clip(tmp_path / "wide.mp4")
    out = tmp_path / "out"
    out.mkdir()
    result = tools.reframe(source, out, "portrait")
    info = probe(result)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    assert json.loads((out / "job.json").read_text())["status"] == "succeeded"
    with pytest.raises(ValueError):
        tools.reframe(source, out, "circle")


def test_prepare_normalizes_to_24_fps_within_the_edge(tmp_path):
    source = clip(tmp_path / "big.mp4", 1280, 720)
    prepared = tools.prepare(source, tmp_path, "upscale")
    video = next(s for s in probe(prepared)["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (960, 540)
    assert video["r_frame_rate"] == "24/1"


@pytest.fixture
def studio(tmp_path, monkeypatch):
    processes = []
    monkeypatch.setenv("COMFY_BASE_URL", "http://127.0.0.1:18291")
    monkeypatch.setenv("COMFY_UPSTREAM_URL", "http://127.0.0.1:18189")

    class Process:
        returncode = None

        def __init__(self, args, **kwargs):
            self.args = args
            processes.append(self)

        def poll(self):
            return self.returncode

    def get(url, **kwargs):
        node = url.rsplit("/", 1)[-1]
        field = "bg_removal_name" if "Background" in node else "model_name"
        data = {node: {"input": {"required": {field: ["COMBO", {"options": []}]}}}}
        return SimpleNamespace(
            status_code=200, json=lambda: data, raise_for_status=lambda: None
        )

    monkeypatch.setattr(app.subprocess, "Popen", Process)
    monkeypatch.setattr(app.httpx, "get", get)
    monkeypatch.setattr(
        app,
        "probe",
        lambda p: {"streams": [{"codec_type": "video"}], "format": {"duration": "6"}},
    )
    monkeypatch.setattr(
        app, "prepare_source", lambda s, d, **o: (d / "source.mp4").write_bytes(b"v")
    )
    client = TestClient(
        app.create_app(tmp_path, "self-hosted", 1), base_url="http://localhost"
    )
    source = client.post("/api/sources", files={"file": ("a.mp4", b"video bytes")})
    return client, processes, source.json()["source_id"]


def test_missing_worker_model_is_explained_and_nothing_runs(studio):
    client, processes, source = studio
    before = len(processes)
    body = {"request_id": "c" * 32, "tool": "fps-boost", "source_id": source}
    response = client.post("/api/tools", json=body)
    assert response.status_code == 503
    assert "rife_v4.26.safetensors (frame_interpolation)" in response.json()["detail"]
    assert "--tool-backend cloud" in response.json()["detail"]
    assert len(processes) == before
    assert client.get("/api/config").json()["tools"]["reframe"] is True


def test_reframe_starts_one_local_run_and_replays(studio):
    client, processes, source = studio
    before = len(processes)
    body = {
        "request_id": "d" * 32,
        "tool": "reframe",
        "source_id": source,
        "target": "square",
    }
    first = client.post("/api/tools", json=body)
    assert first.status_code == 200
    arguments = processes[-1].args
    assert arguments[arguments.index("tool") + 1] == "reframe"
    assert arguments[arguments.index("--target") + 1] == "square"
    assert client.post("/api/tools", json=body).status_code == 200
    assert len(processes) == before + 1
    changed = client.post("/api/tools", json={**body, "fit": "crop"})
    assert changed.status_code == 409
    both = {**body, "request_id": "e" * 32, "take_id": "f" * 32}
    assert client.post("/api/tools", json=both).status_code == 422


def test_depth_map_uses_the_apache_licensed_small_model():
    graph = tools.graph("depth-map")
    assert graph["depth"]["inputs"]["ckpt_name"] == "depth_anything_v2_vits.pth"
    assert graph["fit"]["inputs"]["image"] == ["depth", 0]
    assert graph["video"]["inputs"]["images"] == ["fit", 0]


def silent_clip(path, seconds=1):
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc=size=320x180:rate=24:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def test_join_drops_the_repeated_frame_and_pads_missing_sound(tmp_path):
    first = silent_clip(tmp_path / "take.mp4")
    second = clip(tmp_path / "more.mp4", 320, 180)
    out = tools.join(first, second, tmp_path / "joined.mp4")
    info = probe(out)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    frames = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out),
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    assert int(frames) == 24 + 48 - 1


def test_extend_needs_a_finished_take(studio):
    client, _, source = studio
    body = {"request_id": "9" * 32, "tool": "extend", "source_id": source}
    assert client.post("/api/tools", json=body).status_code == 422
    missing = {"request_id": "8" * 32, "tool": "extend", "take_id": "7" * 32}
    assert client.post("/api/tools", json=missing).status_code == 404


@pytest.mark.parametrize("layout", ["split", "wipe"])
def test_before_after_keeps_the_take_size_length_and_sound(tmp_path, layout):
    original = silent_clip(tmp_path / "source.mp4", 3)
    take = tmp_path / "take.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(take),
        ],
        check=True,
    )  # fmt: skip
    out = tools.compare(original, take, tmp_path / f"{layout}.mp4", layout)
    info = probe(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (640, 360)
    assert abs(float(info["format"]["duration"]) - 3) < 0.15
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    with pytest.raises(ValueError):
        tools.compare(original, take, tmp_path / "x.mp4", "flip")


def test_caption_cues_are_short_upper_case_and_timed():
    from aipg_cinema import captions

    words = [
        {"start": 0.0, "end": 0.3, "word": "Hi!"},
        {"start": 0.4, "end": 0.6, "word": "Today"},
        {"start": 0.6, "end": 0.8, "word": "we"},
        {"start": 0.8, "end": 1.0, "word": "make"},
        {"start": 1.0, "end": 1.3, "word": "pasta."},
        {"start": 2.5, "end": 2.9, "word": "Enjoy"},
    ]
    cues = captions.cues(words)
    assert [text for _, _, text in cues] == ["HI!", "TODAY WE MAKE", "PASTA.", "ENJOY"]
    # Each cue holds until the next one, at most half a second past its words.
    assert cues[0][1] == 0.4 and cues[2][1] == 1.8 and cues[-1][1] == 3.4
    assert captions.srt(cues[:1]) == "1\n00:00:00,000 --> 00:00:00,400\nHI!\n\n"
    assert captions.framing(1080, 1920) == "portrait"
    assert captions.framing(1920, 1080) == "landscape"


def test_captions_is_a_local_tool(tmp_path):
    from fastapi.testclient import TestClient

    from aipg_cinema import app

    client = TestClient(app.create_app(tmp_path / "web"), base_url="http://localhost")
    assert client.get("/api/config").json()["tools"]["captions"] is True
