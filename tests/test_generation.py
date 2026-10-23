import json
import math
import shutil
import struct
import subprocess
import wave
from contextlib import contextmanager
from itertools import pairwise
from types import SimpleNamespace

import pytest
from comfy_sdk.workflows import WorkflowFactory
from PIL import Image

from aipg_cinema import cli, generation, look
from aipg_cinema.reshoot import probe


@pytest.mark.parametrize("mode", ["text", "image", "audio"])
@pytest.mark.parametrize("frame_format", ["portrait", "square", "landscape"])
@pytest.mark.parametrize("closing", [False, True])
def test_starting_modes_keep_two_pass_sampling_without_source_control(
    mode, frame_format, closing
):
    opening = mode == "image" or closing
    graph = generation.graph(
        "A tiny paper sailboat",
        mode=mode,
        frame_format=frame_format,
        opening=opening,
        closing=closing,
    )
    assert WorkflowFactory().from_json(graph).json == graph
    for definition in graph.values():
        for value in definition["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph
    assert not any(
        n["class_type"] in ("LoadVideo", "Canny", "LTXICLoRALoaderModelOnly")
        for n in graph.values()
    )
    assert graph["guider"]["inputs"]["model"] == ["backbone", 0]
    assert graph["refine-guider"]["inputs"]["model"] == ["backbone", 0]
    assert graph["empty"]["inputs"]["length"] == 121
    assert graph["decode"]["inputs"]["samples"] == (
        ["refine-crop", 2] if closing else ["refine-separate", 0]
    )
    if mode == "audio":
        assert graph["empty-audio"]["class_type"] == "SetLatentNoiseMask"
        assert graph["audio-mask"]["inputs"]["value"] == 0
        assert graph["av"]["inputs"]["audio_latent"] == ["empty-audio", 0]
        assert graph["refine-av"]["inputs"]["audio_latent"] == ["empty-audio", 0]
        assert graph["video"]["inputs"]["audio"] == ["source-audio", 0]
    else:
        assert graph["video"]["inputs"]["audio"] == ["decode-audio", 0]
    if closing:
        assert graph["closing-guide"]["inputs"]["positive"] == ["condition", 0]
        assert graph["closing-guide"]["inputs"]["latent"] == ["look-anchor", 0]


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "video"},
        {"mode": "image"},
        {"closing": True},
        {"seed": -1},
        {"seed": True},
        {"seed": 2**63},
        {"frame_format": "invalid"},
    ],
)
def test_invalid_generation_roles_or_settings_reject(options):
    with pytest.raises(ValueError):
        generation.graph("A sailboat", **options)


@pytest.mark.parametrize(
    "frame_format,size",
    [("portrait", (720, 1280)), ("square", (1024, 1024)), ("landscape", (1344, 768))],
)
def test_moss_conditioning_does_not_crop_all_formats_to_landscape(frame_format, size):
    graph = look.graph("Copper and cobalt", frame_format=frame_format)
    assert (
        graph["scale"]["inputs"]["width"],
        graph["scale"]["inputs"]["height"],
    ) == size


def sound_fixture(path, seconds=12):
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        output.writeframes(
            b"".join(
                struct.pack(
                    "<h",
                    round(
                        12000
                        * math.sin(
                            2 * math.pi * (440 if i < 6 * 8000 else 880) * i / 8000
                        )
                    ),
                )
                for i in range(seconds * 8000)
            )
        )
    return path


def frequency(path):
    pcm = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-t",
            "1",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "pipe:1",
        ]
    )
    samples = [item[0] for item in struct.iter_unpack("<h", pcm)]
    return sum((a < 0) != (b < 0) for a, b in pairwise(samples)) / 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_audio_normalization_selects_real_audio_and_only_pads_model_tail(tmp_path):
    original = sound_fixture(tmp_path / "original.wav")
    folder = tmp_path / "run"
    folder.mkdir()
    path = generation.prepare_audio(original, folder, 6)
    with wave.open(str(path)) as audio:
        assert (
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getframerate(),
            audio.getnframes(),
        ) == (2, 2, 48000, 242000)
        audio.setpos(240000)
        assert audio.readframes(2000) == b"\0" * 8000
    assert frequency(path) == pytest.approx(880, abs=5)
    with pytest.raises(ValueError, match="five-second audio section"):
        generation.prepare_audio(original, tmp_path, 8)
    with pytest.raises(ValueError, match="non-negative"):
        generation.prepare_audio(original, tmp_path, float("nan"))
    with pytest.raises(ValueError, match="five seconds"):
        generation.audio_info(sound_fixture(tmp_path / "short.wav", 4))


def test_audio_rejects_playlists_before_a_decoder_runs(tmp_path, monkeypatch):
    source = tmp_path / "remote.m3u8"
    source.write_text("#EXTM3U\nhttps://example.invalid/private\n")

    def unexpected(*args, **kwargs):
        pytest.fail("Unsupported media must not start a decoder")

    monkeypatch.setattr(generation.subprocess, "run", unexpected)
    with pytest.raises(ValueError, match="Choose WAV"):
        generation.audio_info(source)
    assert generation.audio_input(tmp_path / "original.mp4") == [
        "-protocol_whitelist",
        "file",
        "-max_streams",
        "2",
        "-f",
        "mov",
        "-enable_drefs",
        "0",
        "-use_absolute_path",
        "0",
        "-i",
        str(tmp_path / "original.mp4"),
    ]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_export_uses_supplied_audio_not_generated_audio(tmp_path):
    original = sound_fixture(tmp_path / "original.wav")
    generation.prepare_audio(original, tmp_path, 6)
    generated = tmp_path / "generated.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=24:d=5.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=5.2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(generated),
        ],
        check=True,
    )
    output = generation.finish(tmp_path, generated)
    info = probe(output)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert video["nb_frames"] == "120"
    assert float(video["duration"]) == float(audio["duration"]) == 5
    assert audio["sample_rate"] == "48000" and audio["channels"] == 2
    assert frequency(output) == pytest.approx(880, abs=5)
    assert not (tmp_path / "reshoot.partial.mp4").exists()


@pytest.mark.parametrize("mode", ["text", "image", "audio"])
def test_generate_cli_binds_assets_and_recovery_never_resubmits(
    tmp_path, monkeypatch, mode
):
    calls = []

    class Output:
        name, content_type = "video/fixture.mp4", "video/mp4"

        def to_file(self, path):
            path.write_bytes(b"synthetic provider fixture")

    class Job:
        id, status = "existing-generation", "succeeded"

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
    def sdk(*args, **kwargs):
        yield Client()

    monkeypatch.setattr(cli, "sdk_client", sdk)

    def finish(folder, generated):
        output = folder / "reshoot.mp4"
        output.write_bytes(b"synthetic local export")
        return output

    monkeypatch.setattr(generation, "finish", finish)

    def prepare(source, folder, start):
        assert start == 2.5
        output = folder / "source.wav"
        output.write_bytes(b"synthetic normalized audio")
        return output

    monkeypatch.setattr(generation, "prepare_audio", prepare)
    folder = tmp_path / "run"
    command = [
        "generate",
        "--mode",
        mode,
        "--prompt",
        "A sailboat",
        "--format",
        "square",
        "--run-dir",
        str(folder),
        "--execute",
    ]
    if mode == "image":
        image = tmp_path / "opening.png"
        Image.new("RGB", (64, 64), "blue").save(image)
        command += ["--look-frame", str(image)]
    if mode == "audio":
        command += ["--audio", str(tmp_path / "original.wav"), "--source-start", "2.5"]
    assert cli.main(command) == 0
    state = json.loads((folder / "job.json").read_text())
    assert state["generation_mode"] == mode and state["frame_format"] == "square"
    assert state["source_audio"] == ("source.wav" if mode == "audio" else None)
    assert cli.main(command) == 1
    assert cli.main(["resume", str(folder)]) == 0
    assert calls == ["submit", "existing-generation"]
