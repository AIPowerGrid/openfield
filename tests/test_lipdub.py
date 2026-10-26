import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from aipg_cinema import app, lipdub, tools
from aipg_cinema.contracts import ToolRequest


def refs(workflow):
    for key, item in workflow.items():
        for value in item["inputs"].values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
            ):
                yield key, value[0]


@pytest.mark.parametrize("shape", ["portrait", "landscape", "square"])
def test_graph_is_two_passes_with_the_clip_and_its_voice(shape):
    workflow = lipdub.graph("I lost ten grand.", "English", shape, seed=5)
    assert all(target in workflow for _, target in refs(workflow))
    assert workflow["source"]["class_type"] == "LoadVideo"
    assert [k for k, n in workflow.items() if n["class_type"] == "SaveVideo"] == [
        "save"
    ]
    assert workflow["model"]["inputs"]["lora_name"] == lipdub.LORA
    width, height = lipdub.SIZES[shape]
    assert (width // 2) % 32 == 0 and (height // 2) % 32 == 0
    assert workflow["empty"]["inputs"]["width"] == width // 2
    assert workflow["large"]["inputs"]["resize_type.height"] == height
    # The clip's own sound is the speaker reference in both passes.
    assert workflow["voice"]["inputs"]["audio"] == ["parts", 1]
    assert workflow["second-speaker"]["inputs"]["audio_latent"] == ["first-split", 1]
    assert 'saying: "I lost ten grand."' in workflow["positive"]["inputs"]["text"]
    assert workflow["second-noise"]["inputs"]["noise_seed"] == 5


def test_prompt_needs_words_and_a_listed_language():
    assert "speaking in Spanish" in lipdub.prompt("Hola", "Spanish")
    assert '"' not in lipdub.prompt('Say "hi"', "English").split("saying: ")[1][1:-1]
    with pytest.raises(ValueError):
        lipdub.prompt("   ", "English")
    with pytest.raises(ValueError):
        lipdub.prompt("Hi", "Klingon")


def test_tool_request_takes_a_line_only_for_lipdub():
    base = {"request_id": "a" * 32, "source_id": "b" * 32}
    assert ToolRequest(**base, tool="lipdub", line="Hi").language == "English"
    for bad in (
        {"tool": "lipdub"},
        {"tool": "lipdub", "line": "Hi", "language": "Klingon"},
        {"tool": "upscale", "line": "Hi"},
    ):
        with pytest.raises(ValueError):
            ToolRequest(**base, **bad)


def make_clip(path, seconds, sound=True):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc=size=320x568:rate=30:duration={seconds}",
         *(["-f", "lavfi", "-i", f"sine=duration={seconds}"] if sound else []),
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         *(["-c:a", "aac", "-shortest"] if sound else []), str(path)],
        check=True,
    )  # fmt: skip
    return path


def test_prepare_keeps_ten_seconds_and_needs_sound(tmp_path):
    long = make_clip(tmp_path / "long.mp4", 13)
    out = tools.prepare(long, tmp_path, "lipdub")
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    assert int(frames) == 241
    silent = make_clip(tmp_path / "silent.mp4", 2, sound=False)
    with pytest.raises(ValueError):
        tools.prepare(silent, tmp_path / "x", "lipdub")


@pytest.fixture
def studio(tmp_path, monkeypatch):
    processes = []

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
        lambda p: {"streams": [{"codec_type": "video"}], "format": {"duration": "6"}},
    )
    monkeypatch.setattr(
        app, "prepare_source", lambda s, d, **o: (d / "source.mp4").write_bytes(b"v")
    )
    monkeypatch.setenv("COMFY_BASE_URL", "https://cloud.comfy.org")
    monkeypatch.setenv("COMFY_API_KEY", "test-cloud-credential")
    monkeypatch.setattr(
        app.httpx,
        "get",
        lambda url, **k: httpx.Response(200, json={"status": "active"}),
    )
    client = TestClient(
        app.create_app(tmp_path, "cloud", 1, tool_backend="cloud"),
        base_url="http://localhost",
    )
    source = client.post("/api/sources", files={"file": ("a.mp4", b"video bytes")})
    return client, processes, source.json()["source_id"]


def test_transcript_reads_the_first_ten_seconds_once(studio, monkeypatch):
    from aipg_cinema import captions

    client, _, source = studio
    calls = []

    def transcribe(clip):
        calls.append(clip)
        return [
            {"start": 0.2, "end": 0.5, "word": "Bro,"},
            {"start": 0.6, "end": 0.9, "word": "hi"},
            {"start": 11.0, "end": 11.4, "word": "later"},
        ]

    monkeypatch.setattr(captions, "transcribe", transcribe)
    first = client.get(f"/api/transcript?source_id={source}").json()
    assert first == {"text": "Bro, hi", "seconds": lipdub.MAX_SECONDS}
    assert client.get(f"/api/transcript?source_id={source}").json() == first
    assert len(calls) == 1
    assert client.get("/api/transcript").status_code == 422


def test_lipdub_run_sends_the_line_and_language(studio, monkeypatch):
    client, processes, source = studio
    body = {
        "request_id": "c" * 32,
        "tool": "lipdub",
        "source_id": source,
        "line": "Hermano, te enseño cómo.",
        "language": "Spanish",
    }
    assert client.post("/api/tools", json=body).status_code == 200
    arguments = processes[-1].args
    assert arguments[arguments.index("--line") + 1] == "Hermano, te enseño cómo."
    assert arguments[arguments.index("--language") + 1] == "Spanish"


def spoken(*items):
    return [{"word": w, "start": s, "end": e} for w, s, e in items]


def test_changed_span_finds_only_the_edited_words():
    before = spoken(("Bro,", 0, 0.2), ("I", 0.2, 0.4), ("made", 0.4, 0.6),
                    ("10", 0.6, 0.9), ("grand", 0.9, 1.2), ("today.", 1.2, 1.6))  # fmt: skip
    after = spoken(("Bro", 0, 0.2), ("I", 0.2, 0.4), ("made", 0.4, 0.6),
                   ("10", 0.6, 0.9), ("bucks", 0.9, 1.2), ("today", 1.2, 1.6))  # fmt: skip
    assert lipdub.changed_span(before, after) == (4, 5, 4, 5)
    assert lipdub.changed_span(before, before) is None
    assert lipdub.boundary(before, 4, 2.0) == pytest.approx(0.9)
    assert lipdub.boundary(before, 0, 2.0) == 0
    assert lipdub.boundary(before, 6, 2.0) == 2.0


def test_splice_keeps_the_original_around_the_change(tmp_path, monkeypatch):
    from aipg_cinema import captions, reshoot

    source = make_clip(tmp_path / "source.mp4", 3)
    dubbed = make_clip(tmp_path / "dubbed.mp4", 3)
    words = [("a", 0.0, 0.5), ("b", 0.5, 1.0), ("c", 1.0, 1.5), ("d", 1.5, 2.0),
             ("e", 2.0, 2.5), ("f", 2.5, 3.0)]  # fmt: skip
    changed = [*words[:3], ("x", 1.5, 2.0), *words[4:]]
    replies = {source: spoken(*words), dubbed: spoken(*changed)}
    monkeypatch.setattr(captions, "transcribe", lambda clip: replies[clip])
    destination = tmp_path / "out.mp4"
    assert lipdub.splice(source, dubbed, destination) == "spliced"
    length = float(reshoot.probe(destination)["format"]["duration"])
    assert length == pytest.approx(3.0, abs=0.15)
    replies[dubbed] = spoken(("z", 0, 3))
    assert lipdub.splice(source, dubbed, tmp_path / "whole.mp4") == "whole"
