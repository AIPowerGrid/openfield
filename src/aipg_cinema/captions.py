# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 AI Power Grid
"""Auto captions: local Whisper word timings burned in as short social cues.

Speech is transcribed on this machine with faster-whisper (the "small" model
downloads once from Hugging Face; audio never leaves the machine). Words are
grouped into cues of up to three, rendered with the studio's bundled caption
renderer and overlaid at their exact times. An .srt file is written as well.
"""

import json
import subprocess
from pathlib import Path

from .finishing import caption_image
from .reshoot import probe

MODEL_SIZE = "small"
MAX_WORDS = 3
MAX_CUE_SECONDS = 1.6
MAX_SECONDS = 120


def transcribe(media: Path, model_size: str = MODEL_SIZE) -> list[dict]:
    """Every spoken word with its start and end time, in seconds."""
    import numpy
    from faster_whisper import WhisperModel

    # FFmpeg decodes, so faster-whisper never needs its own PyAV decoder.
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(media), "-map", "0:a:0",
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True, capture_output=True, timeout=300,
    ).stdout  # fmt: skip
    audio = numpy.frombuffer(pcm, dtype=numpy.float32)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        audio, word_timestamps=True, vad_filter=True, beam_size=5
    )
    return [
        {"start": word.start, "end": word.end, "word": word.word.strip()}
        for segment in segments
        for word in segment.words or []
        if word.word.strip()
    ]


def cues(words: list[dict]) -> list[tuple[float, float, str]]:
    """Short cues: at most three words, broken at pauses and sentence ends."""
    result, group = [], []

    def flush():
        if group:
            text = " ".join(w["word"] for w in group).upper()
            result.append((group[0]["start"], group[-1]["end"], text))
            group.clear()

    for word in words:
        if group and (
            len(group) >= MAX_WORDS
            or word["start"] - group[-1]["end"] > 0.45
            or word["end"] - group[0]["start"] > MAX_CUE_SECONDS
            or group[-1]["word"][-1:] in ".?!"
        ):
            flush()
        group.append(word)
    flush()
    # Hold each cue until the next one starts (up to half a second longer).
    held = []
    for index, (start, end, text) in enumerate(result):
        following = result[index + 1][0] if index + 1 < len(result) else end + 0.5
        held.append((start, max(end, min(following, end + 0.5)), text))
    return held


def srt(entries: list[tuple[float, float, str]]) -> str:
    def stamp(seconds: float) -> str:
        ms = round(seconds * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    return "".join(
        f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n"
        for index, (start, end, text) in enumerate(entries, start=1)
    )


def framing(width: int, height: int) -> str:
    ratio = width / height
    return "portrait" if ratio < 0.8 else "square" if ratio < 1.25 else "landscape"


def cue_layer(text: str, width: int, height: int, scale: float = 1.7):
    """One cue in the bold caption style, enlarged for social video."""
    from PIL import Image

    image, _ = caption_image(text, framing(width, height), "bold", "lower")
    image = image.resize((width, height))
    box = image.getbbox()
    if not box:
        return image
    text_part = image.crop(box)
    factor = min(scale, width * 0.9 / text_part.width)
    text_part = text_part.resize(
        (round(text_part.width * factor), round(text_part.height * factor)),
        Image.LANCZOS,
    )
    layer = Image.new("RGBA", (width, height))
    top = round(height * 0.74 - text_part.height / 2)
    layer.paste(text_part, ((width - text_part.width) // 2, top), text_part)
    return layer


def burn(source: Path, run_dir: Path) -> Path:
    """Captioned copy of source as tool.mp4, with captions.srt beside it."""
    info = probe(source)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    if not any(s["codec_type"] == "audio" for s in info["streams"]):
        raise ValueError("This clip has no sound to caption.")
    if float(info["format"]["duration"]) > MAX_SECONDS + 0.5:
        raise ValueError("Captions work on clips up to two minutes.")
    entries = cues(transcribe(source))
    if not entries:
        raise ValueError("No speech was found in this clip.")
    (run_dir / "captions.srt").write_text(srt(entries))
    width, height = int(video["width"]), int(video["height"])
    layers = []
    for index, (_, _, text) in enumerate(entries):
        path = run_dir / f"cue-{index:03d}.png"
        cue_layer(text, width, height).save(path)
        layers.append(path)
    inputs, chain, last = [], [], "0:v"
    for index, ((start, end, _), path) in enumerate(zip(entries, layers, strict=True)):
        inputs += ["-i", str(path)]
        out = f"v{index}"
        chain.append(
            f"[{last}][{index + 1}:v]overlay=0:0:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{out}]"
        )
        last = out
    destination = run_dir / "tool.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), *inputs,
            "-filter_complex", ";".join(chain),
            "-map", f"[{last}]", "-map", "0:a:0",
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(destination),
        ],
        check=True,
        timeout=1200,
    )  # fmt: skip
    for path in layers:
        path.unlink()
    (run_dir / "job.json").write_text(
        json.dumps(
            {
                "tool": "captions",
                "status": "succeeded",
                "model": f"faster-whisper {MODEL_SIZE}",
                "cues": len(entries),
                "outputs": [destination.name, "captions.srt"],
                "tool_output": destination.name,
            },
            indent=2,
        )
        + "\n"
    )
    return destination
