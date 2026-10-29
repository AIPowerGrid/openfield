import shutil
import struct
import subprocess
from itertools import pairwise

import pytest
from PIL import Image

from aipg_cinema import reshoot
from aipg_cinema.fixtures import CASES, FRAMES, center, frame, make_fixture
from aipg_cinema.reshoot import finish, graph, prepare_look, prepare_source, probe
from aipg_cinema.review import build


@pytest.mark.parametrize("model", ["h3", "fasth3", "ltx", "ltx25"])
def test_graph_has_an_actual_video_conditioning_path(model):
    workflow = graph(model, "A blue toy car rolls through a desert.")
    for node in workflow.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in workflow
    if model in ("h3", "fasth3"):
        if model == "h3":
            assert "ref2va" in workflow["model"]["inputs"]["unet_name"]
        else:
            assert (
                "fasth3_omniref_qad_nvfp4" in workflow["model"]["inputs"]["unet_name"]
            )
            assert workflow["reference"]["inputs"]["width"] == 1536
            assert workflow["reference"]["inputs"]["height"] == 896
            assert workflow["schedule"]["inputs"]["steps"] == 8
            assert workflow["schedule"]["inputs"]["scheduler"] == "simple"
            assert workflow["guider"]["inputs"]["model"] == ["shift", 0]
            assert workflow["shift"]["inputs"]["shift_video"] == 12.0
            assert workflow["shift"]["inputs"]["shift_audio"] == 3.0
        assert workflow["reference"]["inputs"]["ref_videos.ref_video_0"] == [
            "frames",
            0,
        ]
        assert workflow["sample"]["inputs"]["latent_image"] == ["reference", 1]
    elif model == "ltx":
        assert "ltx-2.3" in workflow["checkpoint"]["inputs"]["ckpt_name"]
        assert workflow["guide"]["inputs"]["image"] == ["edges", 0]
        assert workflow["sample"]["inputs"]["positive"] == ["guide", 0]
    else:
        assert "ltx-2.5" in workflow["backbone"]["inputs"]["unet_name"]
        assert "bf16" in workflow["backbone"]["inputs"]["unet_name"]
        assert "gemma4" in workflow["clip"]["inputs"]["clip_name"]
        assert workflow["model"]["class_type"] == "LTXICLoRALoaderModelOnly"
        assert workflow["guide"]["inputs"]["latent_downscale_factor"] == ["model", 1]
        assert workflow["guide"]["inputs"]["image"] == ["edges", 0]
        assert workflow["guider"]["inputs"]["positive"] == ["guide", 0]
        assert workflow["refine-guider"]["inputs"]["positive"] == ["crop", 0]
        assert workflow["refine-sigmas"]["inputs"]["sigmas"].startswith("0.909375")
        assert workflow["upscale"]["inputs"]["samples"] == ["crop", 2]
    assert "audio" not in workflow["video"]["inputs"]


@pytest.mark.parametrize("case", CASES)
def test_original_fixtures_are_deterministic_and_move(case):
    assert frame(case, 0).tobytes() == frame(case, 0).tobytes()
    assert frame(case, 0).tobytes() != frame(case, 17).tobytes()
    assert center(case, 1) != center(case, 0)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_video_pipeline_retains_source_audio_and_common_duration(tmp_path):
    source = make_fixture("car", tmp_path / "fixture")
    assert int(probe(source)["streams"][0]["nb_frames"]) == FRAMES
    directory = tmp_path / "run"
    directory.mkdir()
    normalized = prepare_source(source, directory)
    silent = directory / "model-output.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(normalized),
            "-an",
            "-c:v",
            "copy",
            str(silent),
        ],
        check=True,
    )
    output = finish(directory, silent)
    info = probe(output)
    assert float(info["format"]["duration"]) == 5
    for stream in info["streams"]:
        assert float(stream["duration"]) == 5
    assert {stream["codec_type"] for stream in info["streams"]} == {"video", "audio"}
    assert output.stat().st_size > 1000
    assert info["format"]["tags"]["title"] == "OpenReshoot - AI-generated video"
    assert info["format"]["tags"]["description"].startswith("AI-generated video")

    def audio_samples(path):
        return subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-t",
                "5",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-f",
                "s16le",
                "pipe:1",
            ]
        )

    before = [s[0] for s in struct.iter_unpack("<h", audio_samples(normalized))]
    after = [s[0] for s in struct.iter_unpack("<h", audio_samples(output))]
    assert len(before) == len(after) == 480000
    correlation = (
        sum(x * y for x, y in zip(before, after, strict=True))
        / (sum(x * x for x in before) * sum(x * x for x in after)) ** 0.5
    )
    assert correlation > 0.98


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_silent_video_export_keeps_exact_picture_clock_without_adding_audio(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=96x96:r=24",
            "-frames:v",
            "124",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    output = finish(tmp_path, source)
    info = probe(output)
    assert len(info["streams"]) == 1
    assert info["streams"][0]["codec_type"] == "video"
    assert int(info["streams"][0]["nb_frames"]) == 120
    assert float(info["streams"][0]["duration"]) == 5


def test_failed_local_export_never_publishes_partial_output(tmp_path, monkeypatch):
    generated = tmp_path / "model-output.mp4"
    header = b"\x00\x00\x00\x18ftypisom"
    generated.write_bytes(header + b"saved provider output")
    source = tmp_path / "source.mp4"
    source.write_bytes(header + b"saved normalized source")

    def interrupted(command, **kwargs):
        partial = tmp_path / "reshoot.partial.mp4"
        assert command[-1] == str(partial)
        assert not (tmp_path / "reshoot.mp4").exists()
        partial.write_bytes(b"interrupted ffmpeg output")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(reshoot.subprocess, "run", interrupted)
    with pytest.raises(subprocess.CalledProcessError):
        finish(tmp_path, generated)
    assert not (tmp_path / "reshoot.mp4").exists()
    assert generated.read_bytes() == header + b"saved provider output"
    assert source.read_bytes() == header + b"saved normalized source"

    def completed(command, **kwargs):
        assert "-y" in command
        (tmp_path / "reshoot.partial.mp4").write_bytes(b"complete local export")

    monkeypatch.setattr(reshoot.subprocess, "run", completed)
    output = finish(tmp_path, generated)
    assert output.read_bytes() == b"complete local export"
    assert not (tmp_path / "reshoot.partial.mp4").exists()
    assert generated.read_bytes() == header + b"saved provider output"


def test_empty_prompt_and_unknown_model_rejected():
    with pytest.raises(ValueError):
        graph("h3", " ")
    with pytest.raises(ValueError):
        graph("unknown", "A blue toy car")


@pytest.mark.parametrize("strength", [-0.01, 1.01, float("nan"), float("inf")])
def test_motion_strength_rejects_invalid_values(strength):
    with pytest.raises(ValueError, match="between zero and one"):
        graph("ltx25", "A blue toy car", motion_strength=strength)


def test_look_frame_anchors_both_passes_without_replacing_motion_guide():
    workflow = graph("ltx25", "A brass pendulum", look_frame=True, motion_strength=0.65)
    assert workflow["guide"]["inputs"]["strength"] == 0.65
    assert workflow["guide"]["inputs"]["image"] == ["edges", 0]
    assert workflow["guide"]["inputs"]["latent"] == ["look-anchor", 0]
    assert workflow["look-anchor"]["inputs"]["latent"] == ["empty", 0]
    assert workflow["refine-look-anchor"]["inputs"]["latent"] == ["upscale", 0]
    assert workflow["refine-av"]["inputs"]["video_latent"] == ["refine-look-anchor", 0]
    assert workflow["refine-look-anchor"]["inputs"]["image"] == ["look", 0]
    assert "look" not in graph("ltx25", "A brass pendulum")


def test_closing_look_retains_motion_and_crops_both_passes():
    workflow = graph("ltx25", "A forest waterfall", look_frame=True, closing_frame=True)
    for definition in workflow.values():
        for value in definition["inputs"].values():
            if isinstance(value, list):
                assert value[0] in workflow
    assert workflow["guide"]["inputs"]["image"] == ["edges", 0]
    for name in ("closing-guide", "refine-closing-guide"):
        assert workflow[name]["class_type"] == "LTXVAddGuide"
        assert workflow[name]["inputs"]["frame_idx"] == 120
        assert workflow[name]["inputs"]["strength"] == 0.7
    assert workflow["av"]["inputs"]["video_latent"] == ["closing-guide", 2]
    assert workflow["crop"]["inputs"]["positive"] == ["closing-guide", 0]
    assert workflow["refine-crop"]["class_type"] == "LTXVCropGuides"
    assert workflow["decode"]["inputs"]["samples"] == ["refine-crop", 2]


@pytest.mark.parametrize("model", ["h3", "fasth3", "ltx", "ltx25"])
def test_closing_look_cannot_be_silently_ignored(model):
    with pytest.raises(ValueError, match="Closing frames require"):
        graph(model, "A forest waterfall", closing_frame=True)
    if model != "ltx25":
        with pytest.raises(ValueError, match="Closing frames require"):
            graph(
                model,
                "A forest waterfall",
                look_frame=model == "fasth3",
                closing_frame=True,
            )


@pytest.mark.parametrize("model", ["h3", "ltx"])
def test_other_models_cannot_silently_ignore_new_controls(model):
    with pytest.raises(ValueError, match="requires ltx25"):
        graph(model, "A brass pendulum", motion_strength=0.5)
    with pytest.raises(ValueError, match="require ltx25"):
        graph(model, "A brass pendulum", look_frame=True)


def test_fasth3_assigns_image_and_video_explicit_roles():
    workflow = graph("fasth3", "A brass pendulum", look_frame=True)
    inputs = workflow["reference"]["inputs"]
    assert inputs["ref_images.ref_image_0"] == ["look", 0]
    assert inputs["ref_videos.ref_video_0"] == ["frames", 0]
    assert "<Picture 1> as the target appearance" in inputs["prompt"]
    assert "<Video 1> only for motion" in inputs["prompt"]
    assert "look" not in graph("fasth3", "A brass pendulum")
    with pytest.raises(ValueError, match="requires ltx25"):
        graph("fasth3", "A brass pendulum", motion_strength=0.5)


def test_look_frame_normalization_is_still_rgb_and_letterboxed(tmp_path):
    source = tmp_path / "portrait.png"
    Image.new("RGBA", (300, 600), "red").save(source)
    directory = tmp_path / "run"
    directory.mkdir()
    output = prepare_look(source, directory)
    with Image.open(output) as normalized:
        assert normalized.size == (1536, 896)
        assert normalized.mode == "RGB"
        assert normalized.getpixel((0, 0)) == (0, 0, 0)
        assert normalized.getpixel((768, 448)) == (255, 0, 0)


def test_closing_image_cannot_overwrite_the_opening_image(tmp_path):
    source = tmp_path / "opening.png"
    end = tmp_path / "end.png"
    Image.new("RGB", (480, 280), "red").save(source)
    Image.new("RGB", (480, 280), "blue").save(end)
    directory = tmp_path / "run"
    directory.mkdir()
    opening = prepare_look(source, directory)
    before = opening.read_bytes()
    closing = prepare_look(end, directory, closing=True)
    assert closing.name == "closing.png"
    assert opening.read_bytes() == before
    with Image.open(closing) as image:
        assert image.getpixel((768, 448)) == (0, 0, 255)


def test_look_frame_rejects_animation_and_large_dimensions(tmp_path):
    source = tmp_path / "animated.webp"
    Image.new("RGB", (10, 10), "red").save(
        source,
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError, match="still image"):
        prepare_look(source, tmp_path)
    source = tmp_path / "large.png"
    Image.new("1", (4001, 4000)).save(source)
    with pytest.raises(ValueError, match="16 megapixels"):
        prepare_look(source, tmp_path)


def test_extreme_image_header_has_a_clear_error_without_decoding(tmp_path, monkeypatch):
    source = tmp_path / "header.png"
    source.write_bytes(b"malformed image fixture")

    def reject_header(*args):
        raise Image.DecompressionBombError("oversized image header")

    monkeypatch.setattr(Image, "open", reject_header)
    with pytest.raises(ValueError, match="16 megapixels"):
        prepare_look(source, tmp_path)
    assert not (tmp_path / "look.png").exists()


def test_review_only_links_existing_clips_without_credentials(tmp_path):
    source = tmp_path / "motion-fixtures" / "car" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"test fixture, not a generated video")
    html = build(tmp_path).read_text()
    assert "motion-fixtures/car/source.mp4" in html
    assert '"url": null' in html
    assert "COMFY_API_KEY" not in html
    assert "__CASES__" not in html


def test_portrait_graph_preserves_native_guides_at_nine_by_sixteen():
    workflow = graph(
        "ltx25",
        "A blue candle",
        frame_format="portrait",
        look_frame=True,
        closing_frame=True,
    )
    assert workflow["empty"]["inputs"]["width"] == 576
    assert workflow["empty"]["inputs"]["height"] == 1024
    assert workflow["empty"]["inputs"]["length"] == 121
    assert workflow["guide"]["inputs"]["image"] == ["edges", 0]
    assert workflow["refine-look-anchor"]["inputs"]["latent"] == ["upscale", 0]
    assert workflow["decode"]["inputs"]["samples"] == ["refine-crop", 2]
    for model in ("h3", "fasth3", "ltx"):
        with pytest.raises(ValueError, match="execution require ltx25"):
            graph(model, "A candle", frame_format="portrait")
    with pytest.raises(ValueError, match="framing"):
        graph("ltx25", "A candle", frame_format="invalid")


def test_portrait_reference_is_not_normalized_to_landscape(tmp_path):
    source = tmp_path / "image.png"
    Image.new("RGB", (288, 512), "blue").save(source)
    destination = prepare_look(source, tmp_path, frame_format="portrait")
    with Image.open(destination) as image:
        assert image.size == (1152, 2048)
        assert image.getpixel((0, 0)) == (0, 0, 255)


@pytest.mark.parametrize("start", [-1, float("nan"), float("inf"), 8])
def test_invalid_source_windows_never_start_ffmpeg(tmp_path, monkeypatch, start):
    monkeypatch.setattr(
        reshoot,
        "probe",
        lambda _: {"format": {"duration": "10"}, "streams": [{"codec_type": "video"}]},
    )

    def unexpected(*args, **kwargs):
        pytest.fail("FFmpeg must not start for an invalid range")

    monkeypatch.setattr(reshoot.subprocess, "run", unexpected)
    with pytest.raises(ValueError, match="source"):
        prepare_source(tmp_path / "original.mp4", tmp_path, source_start=start)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_real_portrait_range_uses_later_frames_and_keeps_audio(tmp_path):
    source = tmp_path / "two-colors.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=180x320:r=24:d=6",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=180x320:r=24:d=6",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=if(lt(t\\,6)\\,sin(2*PI*440*t)\\,sin(2*PI*880*t)):s=48000:d=12",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    folder = tmp_path / "window"
    folder.mkdir()
    normalized = prepare_source(source, folder, frame_format="portrait", source_start=6)
    info = probe(normalized)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (576, 1024)
    assert stream["sample_aspect_ratio"] == "1:1"
    assert int(stream["nb_frames"]) == 124
    pixels = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(normalized),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert pixels[2] > 200 and pixels[0] < 30
    pcm = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(normalized),
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
    samples = [sample[0] for sample in struct.iter_unpack("<h", pcm)]
    crossings = sum((a < 0) != (b < 0) for a, b in pairwise(samples))
    assert 1700 < crossings < 1800  # The later segment is 880 Hz, not 440 Hz.
    output = finish(folder, normalized)
    finished = probe(output)
    assert float(finished["format"]["duration"]) == pytest.approx(5, abs=0.05)
    assert {s["codec_type"] for s in finished["streams"]} == {"video", "audio"}


def test_longer_ltx25_reshoots_scale_every_frame_count():
    from aipg_cinema.reshoot import frames_for, graph

    for seconds in (5, 10, 15):
        frames = frames_for(seconds)
        assert (frames - 1) % 8 == 0
        workflow = graph(
            "ltx25",
            "Restyle the clip.",
            look_frame=True,
            closing_frame=True,
            seconds=seconds,
        )
        assert workflow["source-window"]["inputs"]["length"] == frames
        assert workflow["empty"]["inputs"]["length"] == frames
        assert workflow["empty-audio"]["inputs"]["frames_number"] == frames
        assert workflow["closing-guide"]["inputs"]["frame_idx"] == frames - 1
    with pytest.raises(ValueError, match="require ltx25"):
        graph("ltx", "Restyle the clip.", seconds=10)
    with pytest.raises(ValueError, match="5, 10 or 15"):
        graph("ltx25", "Restyle the clip.", seconds=7)


def test_look_frame_rejects_thumbnails_but_not_the_smallest_photo(tmp_path):
    source = tmp_path / "thumb.png"
    Image.new("RGB", (255, 600), "red").save(source)
    with pytest.raises(ValueError, match="at least 256 pixels wide and tall"):
        prepare_look(source, tmp_path)
    Image.new("RGB", (600, 255), "red").save(source)
    with pytest.raises(ValueError, match="at least 256 pixels wide and tall"):
        prepare_look(source, tmp_path)
    Image.new("RGB", (256, 256), "red").save(source)
    assert prepare_look(source, tmp_path).is_file()
