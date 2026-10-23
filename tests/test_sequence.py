import array
import hashlib
import json
import math
import shutil
import subprocess

import pytest
from test_finishing import sound

from aipg_cinema import sequence
from aipg_cinema.contracts import TakeDraft, TakeRequest
from aipg_cinema.project import AudioLayer, Caption, Project, Shot

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("sequence-takes")
    for number, color, tone in ((1, "red", 440), (2, "green", 880), (3, "blue", None)):
        folder = root / f"{number:032x}"
        (folder / "render").mkdir(parents=True)
        (folder / "request.json").write_text(
            TakeRequest(
                request_id=folder.name,
                mode="text",
                prompt=f"Original {color} fixture",
                frame_format="square",
            ).model_dump_json()
        )
        args = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1280x1280:r=24:d=5",
        ]
        if tone:
            args += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={tone}:sample_rate=48000:duration=5",
                "-ac",
                "2",
                "-c:a",
                "aac",
            ]
        subprocess.run(
            [
                *args,
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(folder / "render" / "reshoot.mp4"),
            ],
            check=True,
            timeout=60,
        )
    return root


def project():
    return Project(
        id="a" * 32,
        frame_format="square",
        title="Three-color short",
        shots=[
            Shot(
                title=name,
                draft=TakeDraft(mode="text", frame_format="square"),
                selected_take_id=f"{index:032x}",
                volume=volume,
            )
            for index, name, volume in (
                (1, "Hook", 0.5),
                (2, "Reveal", 0),
                (3, "Payoff", 1),
            )
        ],
    )


def pcm(path, start=0, duration=1):
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-map",
            "0:a:0",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    samples = array.array("f")
    samples.frombytes(result.stdout)
    return samples


def rms(samples):
    return math.sqrt(sum(value * value for value in samples) / len(samples))


def test_real_fifteen_second_export_order_silence_volume_and_clock(media, tmp_path):
    plan = project()
    output = sequence.assemble(plan, media, tmp_path)
    info = sequence.inspect(output, 1280, 1280, 360, audio_required=True)
    assert info["seconds"] == 15
    colors = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(output),
            "-vf",
            "select=eq(n\\,119)+eq(n\\,120)+eq(n\\,240),scale=1:1",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    assert len(colors) == 9
    assert colors[0] > 180 and colors[1] < 30
    assert colors[4] > 70 and colors[3] < 30
    assert colors[8] > 180 and colors[6] < 30
    original = media / f"{1:032x}" / "render" / "reshoot.mp4"
    assert 0.45 < rms(pcm(output, 1)) / rms(pcm(original, 1)) < 0.55
    assert rms(pcm(output, 6)) < 0.0001
    assert rms(pcm(output, 11)) < 0.0001
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["project"] == plan.model_dump()
    assert [item["take_id"] for item in manifest["takes"]] == [
        f"{i:032x}" for i in (1, 2, 3)
    ]
    assert (
        manifest["takes"][0]["sha256"]
        == hashlib.sha256(original.read_bytes()).hexdigest()
    )
    assert not list(tmp_path.glob(".assembling-*"))
    assert not (tmp_path / "short.partial.mp4").exists()
    assert not (
        tmp_path / "picture.mp4"
    ).exists()  # No redundant clean copy without captions.
    with pytest.raises(ValueError, match="already exists"):
        sequence.assemble(plan, media, tmp_path)


def test_real_caption_frame_boundaries_and_audio_is_copied(media, tmp_path):
    plan = project()
    plan.shots = plan.shots[:1]
    plan.shots[0].trim_end = 60
    plan.captions = [
        Caption(text="FIRST", start_frame=0, end_frame=12),
        Caption(text="SECOND", start_frame=24, end_frame=36),
    ]
    output = sequence.assemble(plan, media, tmp_path)
    assert (
        sequence.inspect(output, 1280, 1280, 60, audio_required=True)["seconds"] == 2.5
    )
    clean = tmp_path / "picture.mp4"
    assert pcm(output, 0, 2.5) == pcm(clean, 0, 2.5)
    selection = "+".join(f"eq(n\\,{n})" for n in (0, 11, 12, 23, 24, 35, 36, 59))
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(output),
            "-vf",
            f"select={selection},crop=900:260:190:800",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    size = 900 * 260 * 3
    assert len(raw) == size * 8
    dark = [
        sum(1 for pixel in range(0, size, 3) if raw[index * size + pixel] < 80)
        for index in range(8)
    ]
    assert [count > 1000 for count in dark] == [
        True,
        True,
        False,
        False,
        True,
        True,
        False,
        False,
    ]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [c["text"] for c in manifest["captions"]] == ["FIRST", "SECOND"]
    assert (
        (tmp_path / "captions.srt")
        .read_text()
        .startswith("1\n00:00:00,000 --> 00:00:00,500")
    )


def test_real_music_voiceover_timing_gain_fades_and_loop(media, tmp_path):
    audio = tmp_path / "audio"
    sound(audio, seconds=1, rate=44100)
    sound(audio, seconds=1, rate=48000, audio_id="c" * 32, frequency=880)
    plan = project()
    plan.shots = plan.shots[:1]
    plan.shots[0].trim_end = 60
    plan.shots[0].volume = 0
    plan.music = AudioLayer(
        audio_id="b" * 32,
        duration_frames=60,
        loop=True,
        volume=0.25,
        fade_in=12,
        fade_out=12,
    )
    plan.voiceover = AudioLayer(
        audio_id="c" * 32, start_frame=24, duration_frames=24, volume=0.5
    )
    output = sequence.assemble(plan, media, tmp_path / "export", audio)
    assert (
        sequence.inspect(output, 1280, 1280, 60, audio_required=True)["seconds"] == 2.5
    )

    def component(start, frequency):
        values = pcm(output, start, 0.25)[::2]
        n = len(values)
        return (
            2
            * math.hypot(
                sum(
                    v * math.cos(2 * math.pi * frequency * i / 48000)
                    for i, v in enumerate(values)
                ),
                sum(
                    v * math.sin(2 * math.pi * frequency * i / 48000)
                    for i, v in enumerate(values)
                ),
            )
            / n
        )

    assert component(1.25, 880) > 0.05
    assert component(0.6, 880) < 0.001
    assert component(2.1, 880) < 0.001
    assert 0.025 < component(0.6, 440) < 0.04
    assert rms(pcm(output, 0.0, 0.1)) < rms(pcm(output, 0.6, 0.1)) * 0.25
    assert rms(pcm(output, 2.4, 0.1)) < rms(pcm(output, 0.6, 0.1)) * 0.25
    receipt = json.loads((output.parent / "manifest.json").read_text())
    assert [layer["role"] for layer in receipt["audio_layers"]] == [
        "music",
        "voiceover",
    ]


def test_exact_frame_trim_and_reordering_use_selected_not_newest(media, tmp_path):
    plan = project()
    plan.shots = [plan.shots[2], plan.shots[0]]
    plan.shots[0].trim_start = 24
    plan.shots[0].trim_end = 59
    plan.shots[1].trim_start = 48
    plan.shots[1].trim_end = 72
    output = sequence.assemble(plan, media, tmp_path)
    assert sequence.inspect(output, 1280, 1280, 59, audio_required=True)["frames"] == 59
    assert [
        item["take_id"]
        for item in json.loads((tmp_path / "manifest.json").read_text())["takes"]
    ] == [f"{3:032x}", f"{1:032x}"]


def test_failed_export_keeps_takes_and_does_not_publish_partial(
    media, tmp_path, monkeypatch
):
    actual = sequence.run

    def fail(arguments, timeout=180):
        if "-filter_complex" in arguments:
            (tmp_path / "short.partial.mp4").write_bytes(b"incomplete encode")
            raise subprocess.CalledProcessError(1, "ffmpeg")
        return actual(arguments, timeout)

    monkeypatch.setattr(sequence, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        sequence.assemble(project(), media, tmp_path)
    assert not (tmp_path / "short.mp4").exists()
    assert not (tmp_path / "short.partial.mp4").exists()
    assert not list(tmp_path.glob(".assembling-*"))
    assert (media / f"{1:032x}" / "render" / "reshoot.mp4").is_file()


def test_missing_selection_or_wrong_framing_fails_closed(media, tmp_path):
    plan = project()
    plan.shots[0].selected_take_id = None
    with pytest.raises(ValueError, match="every shot"):
        sequence.assemble(plan, media, tmp_path)
    plan = project()
    plan.frame_format = "portrait"
    for shot in plan.shots:
        shot.draft.frame_format = "portrait"
    with pytest.raises(ValueError, match="framing"):
        sequence.assemble(plan, media, tmp_path)
    assert not (tmp_path / "short.mp4").exists()


def test_metadata_failure_does_not_publish_an_incomplete_export(
    media, tmp_path, monkeypatch
):
    original = sequence.atomic_json

    def fail(path, value):
        if path.name == "quality.json":
            raise OSError("test disk failure")
        original(path, value)

    monkeypatch.setattr(sequence, "atomic_json", fail)
    plan = project()
    plan.shots = plan.shots[:1]
    plan.shots[0].trim_end = 24
    with pytest.raises(OSError, match="disk failure"):
        sequence.assemble(plan, media, tmp_path)
    assert not (tmp_path / "short.mp4").exists()
    assert not (tmp_path / "short.partial.mp4").exists()
