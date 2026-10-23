# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Bounded offline sound layers and caption images, never inference."""

import hashlib
import html
import json
import os
import subprocess
import threading
import wave
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .generation import AUDIO_FORMATS, audio_info, audio_input
from .project import AudioLayer, Project
from .reshoot import video_format

FONT_ROOT = Path(__file__).with_name("fonts")
_FONT_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def coverage() -> dict:
    data = json.loads((FONT_ROOT / "coverage.json").read_text())
    if (
        hashlib.sha256((FONT_ROOT / "NotoSans.ttf").read_bytes()).hexdigest()
        != data["sha256"]
    ):
        raise ValueError("The bundled caption font failed its integrity check.")
    return data


@lru_cache(maxsize=16)
def font(size: int, weight: int):
    value = ImageFont.truetype(str(FONT_ROOT / "NotoSans.ttf"), size)
    value.set_variation_by_axes([weight, 100])
    return value


def _lines(text: str, face, width: int) -> list[str]:
    result = []
    for paragraph in text.expandtabs(4).splitlines():
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if face.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                result.append(line)
                line = ""
            for character in word:
                if line and face.getlength(line + character) > width:
                    result.append(line)
                    line = ""
                line += character
        if line:
            result.append(line)
    return result


def caption_image(
    text: str, frame_format: str, style: str = "clean", position: str = "lower"
) -> tuple[Image.Image, dict]:
    if style not in ("clean", "bold", "studio") or position not in (
        "lower",
        "center",
        "upper",
    ):
        raise ValueError("Choose a supported caption style and position.")
    if not text.strip() or len(text) > 160:
        raise ValueError("Use 1 to 160 characters per caption.")
    if any(not c.isprintable() and c not in "\n\t" for c in text):
        raise ValueError("Caption text contains unsupported control characters.")
    data = coverage()
    if any(
        not character.isspace()
        and not any(start <= ord(character) <= end for start, end in data["ranges"])
        for character in text
    ):
        raise ValueError(
            "This caption uses characters outside the bundled font. Use supported letters and punctuation, without emoji."
        )
    if style == "studio":
        return _studio_caption(text, frame_format, position)
    width, height = video_format(frame_format).output_size
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    base = round(min(width * 0.055, height * 0.04) * (1.15 if style == "bold" else 1))
    padding = round(width * 0.018)
    with _FONT_LOCK:
        for size in range(base, max(17, round(base * 0.65)) - 1, -1):
            face = font(size, 800 if style == "bold" else 650)
            lines = _lines(text, face, round(width * 0.78))
            stroke = max(2, round(size * 0.055))
            spacing = round(size * 0.24)
            content = "\n".join(lines)
            box = draw.multiline_textbbox(
                (0, 0),
                content,
                font=face,
                spacing=spacing,
                stroke_width=stroke,
                align="center",
            )
            tw, th = box[2] - box[0], box[3] - box[1]
            if (
                len(lines) <= 4
                and tw + 2 * padding <= width * 0.84
                and th + 2 * padding <= height * 0.20
            ):
                break
        else:
            raise ValueError(
                "This caption is too long for readable placement. Split it into shorter cues."
            )
        # Upper cues clear a centered product and stay below the top UI band
        # (the caption box is at most a fifth of the frame tall).
        center = height * {"lower": 0.72, "center": 0.48, "upper": 0.24}[position]
        bounds = (
            round((width - tw) / 2 - padding),
            round(center - th / 2 - padding),
            round((width + tw) / 2 + padding),
            round(center + th / 2 + padding),
        )
        if style == "clean":
            draw.rounded_rectangle(bounds, radius=8, fill=(8, 10, 12, 190))
        draw.multiline_text(
            ((width - tw) / 2 - box[0], center - th / 2 - box[1]),
            content,
            font=face,
            fill="#ffe36e" if style == "bold" else "white",
            stroke_width=stroke,
            stroke_fill="#101214",
            align="center",
            spacing=spacing,
        )
    return image, {
        "width": width,
        "height": height,
        "bounds": bounds,
        "font_size": size,
        "lines": lines,
        "font_sha256": data["sha256"],
    }


CAPTION_CENTERS = {"lower": 0.72, "center": 0.48, "upper": 0.24}


def _studio_caption(
    text: str, frame_format: str, position: str
) -> tuple[Image.Image, dict]:
    """Heavy Montserrat with a soft shadow and no box: a social-ad look that
    stays readable over bright footage. Falls back to Noto Sans per caption."""
    from .typography import LOCK, covers, face, manifest, stack, text_layer, wrap

    width, height = video_format(frame_format).output_size
    base = round(min(width * 0.064, height * 0.044))
    with _FONT_LOCK, LOCK:
        for size in range(base, max(17, round(base * 0.6)) - 1, -1):
            typeface = face("montserrat", text, size, 800)
            lines = [
                line
                for paragraph in text.expandtabs(4).splitlines()
                for line in wrap(paragraph, typeface, round(width * 0.8), 0.01)
            ]
            shadow = max(2, round(size * 0.12))
            block = stack(
                [
                    text_layer(
                        line,
                        typeface,
                        (255, 255, 255),
                        tracking=0.01,
                        shadow=shadow,
                        shadow_alpha=235,
                    )
                    for line in lines
                ],
                round(size * 0.28),
            )
            if (
                len(lines) <= 3
                and block.width <= width * 0.9
                and block.height <= height * 0.2
            ):
                break
        else:
            raise ValueError(
                "This caption is too long for readable placement. Split it into shorter cues."
            )
    image = Image.new("RGBA", (width, height))
    center = height * CAPTION_CENTERS[position]
    left, top = round((width - block.width) / 2), round(center - block.height / 2)
    # A soft dark scrim keeps white type readable over bright footage
    # without the hard box of the clean style.
    scrim = Image.new("L", (width, height))
    spread = round(size * 1.1)
    ImageDraw.Draw(scrim).rounded_rectangle(
        (
            left - spread,
            top - spread // 2,
            left + block.width + spread,
            top + block.height + spread // 2,
        ),
        radius=spread,
        fill=105,
    )
    dark = Image.new("RGBA", (width, height), (6, 8, 10, 0))
    dark.putalpha(scrim.filter(ImageFilter.GaussianBlur(spread * 0.8)))
    image.alpha_composite(dark)
    image.alpha_composite(block, (left, top))
    montserrat = covers("montserrat", text)
    return image, {
        "width": width,
        "height": height,
        "bounds": (left, top, left + block.width, top + block.height),
        "font_size": size,
        "lines": lines,
        "font_sha256": manifest()["montserrat"]["sha256"]
        if montserrat
        else coverage()["sha256"],
    }


def validate_finish(project: Project) -> None:
    previous_end = 0
    for number, caption in enumerate(
        sorted(project.captions, key=lambda cue: cue.start_frame), 1
    ):
        if caption.start_frame < previous_end or caption.end_frame > project.frames:
            raise ValueError(
                f"Caption {number} overlaps another cue or extends beyond the short."
            )
        previous_end = caption.end_frame
        caption_image(
            caption.text,
            project.frame_format,
            project.caption_style,
            project.caption_position,
        )
    for role in ("music", "voiceover"):
        layer = getattr(project, role)
        if layer and layer.start_frame + layer.duration_frames > project.frames:
            raise ValueError(f"The {role} layer extends beyond the short.")
        if role == "voiceover" and layer and layer.loop:
            raise ValueError(
                "Voiceover cannot loop. Use the music layer for repeating sound."
            )


def layer_path(root: Path, audio_id: str) -> Path:
    from .assets import asset_folder

    metadata = asset_folder(root, audio_id) / "audio.json"
    data = json.loads(metadata.read_text())
    suffix = data["suffix"]
    path = metadata.parent / ("original" + suffix)
    if (
        suffix not in AUDIO_FORMATS
        or not path.resolve().is_relative_to(metadata.parent.resolve())
        or not path.is_file()
    ):
        raise ValueError("The soundtrack input is missing or unsupported.")
    return path


def prepare_layer(
    root: Path, layer: AudioLayer, directory: Path, role: str
) -> tuple[Path, dict]:
    original = layer_path(root, layer.audio_id)
    frozen = directory / (role + "-input" + original.suffix)
    digest = hashlib.sha256()
    with original.open("rb") as source, frozen.open("xb") as output:
        size = 0
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > 50 * 1024 * 1024:
                raise ValueError("Soundtrack input exceeds 50 MB.")
            digest.update(chunk)
            output.write(chunk)
    info = audio_info(frozen, min_duration=0.1)
    stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    duration = float(stream.get("duration") or info["format"]["duration"])
    available = duration - layer.source_start
    requested = layer.duration_frames * 2000
    if available <= 0 or (not layer.loop and available + 1 / 48000 < requested / 48000):
        raise ValueError(
            f"The {role} source does not cover this selection. Shorten it or adjust its source start."
        )
    samples = min(requested, max(1, round(available * 48000)))
    cycle = directory / (role + "-cycle.wav")
    env = {"PATH": os.environ.get("PATH", os.defpath)}
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            str(layer.source_start),
            *audio_input(frozen),
            "-map",
            "0:a:0",
            "-af",
            f"aresample=48000,atrim=end_sample={samples}",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(cycle),
        ],
        check=True,
        timeout=90,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    with wave.open(str(cycle)) as audio:
        actual = audio.getnframes()
        if not actual or (not layer.loop and actual < requested):
            raise ValueError(
                f"The decoded {role} source is shorter than its requested section."
            )
    normalized = directory / (role + ".wav")
    filters = (
        f"aloop=loop=-1:size={actual}," if layer.loop else ""
    ) + f"apad=whole_len={requested},atrim=end_sample={requested},asetpts=N/(48000*TB)"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-f",
            "wav",
            "-i",
            str(cycle),
            "-af",
            filters,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(normalized),
        ],
        check=True,
        timeout=90,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    with wave.open(str(normalized)) as audio:
        if (audio.getnframes(), audio.getframerate(), audio.getnchannels()) != (
            requested,
            48000,
            2,
        ):
            raise ValueError("The normalized soundtrack clock is invalid.")
    return normalized, {
        "role": role,
        "source_sha256": digest.hexdigest(),
        "settings": layer.model_dump(),
        "samples_per_channel": requested,
    }


def audio_graph(layer: AudioLayer, index: int, name: str, total_frames: int) -> str:
    filters = f"[{index}:a]volume={layer.volume},"
    if layer.fade_in:
        filters += f"afade=t=in:ss=0:ns={layer.fade_in * 2000},"
    if layer.fade_out:
        filters += f"afade=t=out:ss={(layer.duration_frames - layer.fade_out) * 2000}:ns={layer.fade_out * 2000},"
    filters += f"adelay=delays={layer.start_frame * 2000}S:all=1,apad=whole_len={total_frames * 2000},atrim=end_sample={total_frames * 2000},asetpts=N/(48000*TB)[{name}]"
    return filters


def subtitles(project: Project) -> str:
    def clock(frame):
        value = round(frame * 1000 / 24)
        hours, value = divmod(value, 3600000)
        minutes, value = divmod(value, 60000)
        seconds, milliseconds = divmod(value, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

    return "\n".join(
        f"{number}\n{clock(caption.start_frame)} --> {clock(caption.end_frame)}\n{html.escape(caption.text)}\n"
        for number, caption in enumerate(
            sorted(project.captions, key=lambda cue: cue.start_frame), 1
        )
    )
