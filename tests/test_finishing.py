import array
import io
import json
import math
import shutil
import wave

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from aipg_cinema.app import create_app
from aipg_cinema.finishing import (
    FONT_ROOT,
    caption_image,
    prepare_layer,
    subtitles,
    validate_finish,
)
from aipg_cinema.project import AudioLayer, Caption, Project, Shot


def plan():
    return Project(id="a" * 32, shots=[Shot()], frame_format="landscape")


def sound(root, seconds=1, rate=44100, audio_id="b" * 32, frequency=440):
    folder = root / audio_id
    folder.mkdir(parents=True)
    path = folder / "original.wav"
    samples = array.array(
        "h",
        (
            round(6000 * math.sin(2 * math.pi * frequency * i / rate))
            for i in range(round(seconds * rate))
        ),
    )
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(samples.tobytes())
    (folder / "audio.json").write_text(
        json.dumps(
            {
                "audio_id": folder.name,
                "suffix": ".wav",
                "name": "Original test tone",
                "duration": seconds,
            }
        )
    )
    return path


@pytest.mark.parametrize("framing", ["portrait", "square", "landscape"])
@pytest.mark.parametrize("style", ["clean", "bold"])
def test_caption_font_and_readable_bounds(framing, style):
    text = "A tiny beginning. An unexpected world."
    image, layout = caption_image(text, framing, style)
    left, top, right, bottom = image.getbbox()
    width, height = image.size
    assert left >= width * 0.075 and right <= width * 0.925
    assert top >= height * 0.60 and bottom <= height * 0.85
    assert len(layout["font_sha256"]) == 64
    assert " ".join(layout["lines"]) == text
    assert layout["font_size"] >= 17


def test_caption_supports_accents_long_words_and_rejects_tofu_and_controls():
    image, layout = caption_image("Café: déjà vu. München!", "portrait")
    assert image.getbbox() and layout["lines"]
    assert caption_image("UnusuallyLongButStillReadable" * 3, "portrait")[0].getbbox()
    for text in ("An emoji \U0001f680", "a\x00b", "a\u202eb"):
        with pytest.raises(ValueError):
            caption_image(text, "portrait")
    for text in ("", " " * 10, "word " * 33):
        with pytest.raises(ValueError):
            caption_image(text, "square")


def test_caption_font_keeps_its_own_license_in_installed_packages():
    license = (FONT_ROOT / "OFL.txt").read_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in license
    assert "Noto Project Authors" in license
    assert "not relicensed under MIT" in (FONT_ROOT / "README.md").read_text()


def test_finishing_contract_and_exact_srt_times():
    project = plan()
    project.captions = [
        Caption(text="A < B & C", start_frame=0, end_frame=24),
        Caption(text="Second", start_frame=25, end_frame=120),
    ]
    validate_finish(project)
    assert (
        subtitles(project)
        == "1\n00:00:00,000 --> 00:00:01,000\nA &lt; B &amp; C\n\n2\n00:00:01,042 --> 00:00:05,000\nSecond\n"
    )
    project.captions[1].start_frame = 23
    with pytest.raises(ValueError, match="overlaps"):
        validate_finish(project)
    project.captions = []
    project.music = AudioLayer(audio_id="b" * 32, duration_frames=121)
    with pytest.raises(ValueError, match="beyond"):
        validate_finish(project)
    project.music = None
    project.voiceover = AudioLayer(audio_id="b" * 32, duration_frames=24, loop=True)
    with pytest.raises(ValueError, match="cannot loop"):
        validate_finish(project)
    for values in (
        {"duration_frames": 24, "fade_in": 13, "fade_out": 12},
        {"duration_frames": 1.5},
        {"duration_frames": 24, "volume": float("nan")},
    ):
        with pytest.raises(ValidationError):
            AudioLayer(audio_id="b" * 32, **values)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_short_audio_range_resamples_then_loops_exactly(tmp_path):
    root = tmp_path / "audio"
    original = sound(root, seconds=1, rate=44100)
    target = tmp_path / "render"
    target.mkdir()
    settings = AudioLayer(
        audio_id="b" * 32, source_start=0.25, duration_frames=60, loop=True
    )
    output, receipt = prepare_layer(root, settings, target, "music")
    with wave.open(str(output)) as stream:
        assert (stream.getnframes(), stream.getframerate(), stream.getnchannels()) == (
            120000,
            48000,
            2,
        )
        samples = array.array("h", stream.readframes(120000))
    assert 4000 < max(map(abs, samples)) < 4500  # FFmpeg mono-to-stereo gain.
    # The cycle starts at the selected source offset and repeats sample-for-sample.
    assert samples[:72000] == samples[72000:144000]
    assert receipt["settings"] == settings.model_dump()
    assert original.is_file()
    failed = tmp_path / "failed"
    failed.mkdir()
    with pytest.raises(ValueError, match="does not cover"):
        prepare_layer(
            root, AudioLayer(audio_id="b" * 32, duration_frames=60), failed, "voiceover"
        )


def test_caption_preview_api_uses_the_export_renderer_and_rejects_foreign_origin(
    tmp_path,
):
    web = TestClient(create_app(tmp_path), base_url="http://localhost")
    body = {
        "text": "One small beginning.",
        "frame_format": "portrait",
        "style": "bold",
        "position": "lower",
    }
    response = web.post("/api/caption-previews", json=body)
    assert response.status_code == 200
    item = response.json()
    result = web.get(item["url"])
    image = Image.open(io.BytesIO(result.content))
    expected, layout = caption_image(body["text"], "portrait", "bold")
    assert image.tobytes() == expected.tobytes()
    assert item["layout"]["font_sha256"] == layout["font_sha256"]
    assert web.post("/api/caption-previews", json=body).json() == item
    assert (
        web.post(
            "/api/caption-previews",
            json=body,
            headers={"origin": "https://elsewhere.test"},
        ).status_code
        == 403
    )
    assert (
        web.post(
            "/api/caption-previews", json={**body, "text": "\U0001f680"}
        ).status_code
        == 400
    )
    assert web.get("/api/caption-previews/not-an-id").status_code == 404
    assert web.get("/finishing.js").status_code == 200


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_soundtrack_upload_accepts_short_voice_without_weakening_conditioning(tmp_path):
    path = sound(tmp_path / "fixtures", seconds=0.5)
    web = TestClient(create_app(tmp_path / "studio"), base_url="http://localhost")
    data = path.read_bytes()
    assert (
        web.post(
            "/api/audio", files={"file": ("voice.wav", data, "audio/wav")}
        ).status_code
        == 400
    )
    response = web.post(
        "/api/audio?purpose=soundtrack",
        files={"file": ("voice.wav", data, "audio/wav")},
    )
    assert response.status_code == 200
    audio_id = response.json()["audio_id"]
    result = web.get(f"/api/audio/{audio_id}/soundtrack?frames=12")
    assert result.status_code == 200
    with wave.open(io.BytesIO(result.content)) as stream:
        assert (stream.getnframes(), stream.getframerate()) == (24000, 48000)
    assert web.get(f"/api/audio/{audio_id}/soundtrack?frames=24").status_code == 400
    assert web.get(f"/api/audio/{audio_id}").status_code == 400
    assert not list(
        (tmp_path / "studio/audio").glob("*/soundtrack-previews/.preparing-*")
    )
